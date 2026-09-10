-- ---------------------------------------------------------------------------
-- sportlogiq schema v2
--
-- Replaces the v1 schema. Written against a merged event vocabulary: one
-- `event` table holding playsequence_compiled events with the
-- playsequence.json-only fields linked across (RawGame.LINKED_FIELDS), which
-- is what build_game now produces by default.
--
-- What changed from v1 and why (each verified against the data, see notes):
--
--  1. ONE event table. v1 had `event` and `compiled_event`; the compiled
--     vocabulary is a superset of the plain one apart from "whistle", and
--     whistle is recoverable (509/523 coincide exactly with a faceoff time,
--     the other 14 sit on period boundaries).
--
--  2. sl_event_id is VARCHAR, not INT. Derived events carry composite ids
--     ("6069038669-356139072"). v1 parsed them with int() and silently stored
--     NULL -- 2435 of 6036 events in a sample game, i.e. every derived event.
--
--  3. game_time is DOUBLE, not FLOAT. v1's FLOAT truncated 947.36664 to
--     947.367, which differed from the JSON path on 4143 of 6220 events.
--
--  4. No comma-joined lists. v1 stored `flags` as varchar(255) and the on-ice
--     refs as comma-joined varchars, which forced _split_flags/_parse_refs in
--     the loader. Flags now live in event_flag; on-ice is derived from shift.
--
--  5. No on-ice columns at all. The on-ice set is functionally determined by
--     `shift`: reconstructing it from the intervals matched the supplier's
--     refs on 5029/5031 sampled events, with both differences explained by
--     interval-edge rounding. Storing it too would be a second source of
--     truth for 70,383 rows per game (~40M rows at 562 games).
--     If line-combination queries later justify it, add a DERIVED
--     player_on_ice table rebuilt from shift -- as a cache, never as truth.
--
--  6. Column names match the supplier's JSON keys, so the loader is a
--     straight mapping: game_time (not t), expected_goals_all_shots_grade
--     (not grade), manpower_situation (underscored, as playsequence spells
--     it -- compiled's "manpowersituation" alias is normalised on ingest).
-- ---------------------------------------------------------------------------

SET FOREIGN_KEY_CHECKS = 0;

-- --- Reference data --------------------------------------------------------

CREATE TABLE `league` (
  `id`      INT NOT NULL AUTO_INCREMENT,
  `sl_id`   INT NOT NULL,
  `name`    VARCHAR(100) NOT NULL,
  `sl_name` VARCHAR(100) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `league_sl_id` (`sl_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `team` (
  `id`       INT NOT NULL AUTO_INCREMENT,
  `sl_id`    INT NOT NULL,
  `name`     VARCHAR(100) NOT NULL,
  `location` VARCHAR(100) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `team_sl_id` (`sl_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `player` (
  `id`         INT NOT NULL AUTO_INCREMENT,
  `sl_id`      INT NOT NULL,
  `first_name` VARCHAR(100) DEFAULT NULL,
  `last_name`  VARCHAR(100) DEFAULT NULL,
  `birthdate`  DATE DEFAULT NULL,
  `nationality` VARCHAR(45) DEFAULT NULL,
  `height`     SMALLINT DEFAULT NULL,
  `weight`     SMALLINT DEFAULT NULL,
  `laterality` VARCHAR(4) DEFAULT NULL,
  `updated_on` DATETIME DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `player_sl_id` (`sl_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `game` (
  `id`               INT NOT NULL AUTO_INCREMENT,
  `sl_id`            INT NOT NULL,
  `league_id`        INT NOT NULL,
  `season`           VARCHAR(20) NOT NULL,
  `stage`            VARCHAR(45) DEFAULT NULL,
  `home_team_id`     INT NOT NULL,
  `away_team_id`     INT NOT NULL,
  `scheduled_time`   DATETIME DEFAULT NULL,
  `home_team_goals`  TINYINT UNSIGNED DEFAULT NULL,
  `away_team_goals`  TINYINT UNSIGNED DEFAULT NULL,
  `event_status`     VARCHAR(45) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `game_sl_id` (`sl_id`),
  -- the access path for every season-wide query
  KEY `game_league_season` (`league_id`, `season`, `scheduled_time`),
  KEY `game_home_team` (`home_team_id`),
  KEY `game_away_team` (`away_team_id`),
  CONSTRAINT `fk_game_league` FOREIGN KEY (`league_id`) REFERENCES `league` (`id`),
  CONSTRAINT `fk_game_home_team` FOREIGN KEY (`home_team_id`) REFERENCES `team` (`id`),
  CONSTRAINT `fk_game_away_team` FOREIGN KEY (`away_team_id`) REFERENCES `team` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Which players dressed for which team in which game, and in what position.
-- Position is per game, so this is where a query joins to learn whether the
-- player on the ice was a forward, a defenceman or a goalie.
CREATE TABLE `affiliation` (
  `id`             INT NOT NULL AUTO_INCREMENT,
  `game_id`        INT NOT NULL,
  `player_id`      INT NOT NULL,
  `team_id`        INT NOT NULL,
  `position`       VARCHAR(6) DEFAULT NULL,
  `jersey_number`  SMALLINT DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `affiliation_game_player` (`game_id`, `player_id`),
  KEY `affiliation_player_game` (`player_id`, `game_id`),
  KEY `affiliation_team_game` (`team_id`, `game_id`),
  CONSTRAINT `fk_affiliation_game` FOREIGN KEY (`game_id`) REFERENCES `game` (`id`),
  CONSTRAINT `fk_affiliation_player` FOREIGN KEY (`player_id`) REFERENCES `player` (`id`),
  CONSTRAINT `fk_affiliation_team` FOREIGN KEY (`team_id`) REFERENCES `team` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- --- Shifts: the single source of truth for who was on the ice ------------

CREATE TABLE `shift` (
  `id`        BIGINT NOT NULL AUTO_INCREMENT,
  `game_id`   INT NOT NULL,
  `player_id` INT NOT NULL,
  `period`    TINYINT UNSIGNED DEFAULT NULL,
  `in_time`   DOUBLE NOT NULL,
  `out_time`  DOUBLE DEFAULT NULL,   -- NULL only for a shift open at game end
  PRIMARY KEY (`id`),
  -- the on-ice interval join: narrow to one player's ~25 shifts, then range
  KEY `shift_player_game_in` (`player_id`, `game_id`, `in_time`),
  -- the reverse direction: everyone on the ice during a window of one game
  KEY `shift_game_in_out` (`game_id`, `in_time`, `out_time`),
  CONSTRAINT `fk_shift_game` FOREIGN KEY (`game_id`) REFERENCES `game` (`id`),
  CONSTRAINT `fk_shift_player` FOREIGN KEY (`player_id`) REFERENCES `player` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- --- Events ----------------------------------------------------------------

CREATE TABLE `event` (
  `id`                 BIGINT NOT NULL AUTO_INCREMENT,
  `game_id`            INT NOT NULL,

  -- Supplier ids. VARCHAR because derived events carry "<child>-<base>".
  -- sl_base_event_id is plain on every event seen, but kept the same width
  -- so a future composite does not truncate.
  `sl_event_id`        VARCHAR(32) NOT NULL,
  `sl_base_event_id`   VARCHAR(32) DEFAULT NULL,

  `game_time`          DOUBLE NOT NULL,
  `period`             TINYINT UNSIGNED DEFAULT NULL,
  `period_time`        DOUBLE DEFAULT NULL,

  `name`               VARCHAR(40) NOT NULL,   -- 48 distinct
  `type`               VARCHAR(60) DEFAULT NULL,  -- 136 distinct
  `outcome`            ENUM('successful','failed','undetermined') DEFAULT NULL,
  `shorthand`          VARCHAR(60) DEFAULT NULL,  -- supplier's plain-language label

  -- Actors. player_id is the event's own player, NOT who was on the ice.
  `team_id`            INT DEFAULT NULL,
  `player_id`          INT DEFAULT NULL,
  `team_in_possession` INT DEFAULT NULL,

  -- Location
  `zone`               ENUM('dz','nz','oz') DEFAULT NULL,
  `play_zone`          ENUM('dz','nz','oz') DEFAULT NULL,
  `play_section`       VARCHAR(30) DEFAULT NULL,  -- 23 distinct
  `x_adj_coord`        DOUBLE DEFAULT NULL,       -- reflected: possession attacks right
  `y_adj_coord`        DOUBLE DEFAULT NULL,

  -- Possession structure
  `current_possession`         INT DEFAULT NULL,
  `current_play_in_possession` INT DEFAULT NULL,
  `is_possession_event`        BOOLEAN DEFAULT NULL,
  `is_last_play_of_possession` BOOLEAN DEFAULT NULL,
  `is_possession_breaking`     BOOLEAN DEFAULT NULL,
  `is_defensive_event`         BOOLEAN DEFAULT NULL,

  -- Situation
  `team_skaters_on_ice`          TINYINT UNSIGNED DEFAULT NULL,
  `opposing_team_skaters_on_ice` TINYINT UNSIGNED DEFAULT NULL,
  `manpower_situation`           ENUM('evenStrength','powerPlay','shortHanded') DEFAULT NULL,
  `score_differential`           TINYINT DEFAULT NULL,

  -- Expected goals
  `expected_goals_all_shots`       DOUBLE DEFAULT NULL,
  `expected_goals_all_shots_grade` CHAR(1) DEFAULT NULL,
  `expected_goals_on_net`          DOUBLE DEFAULT NULL,
  `expected_goals_on_net_grade`    CHAR(1) DEFAULT NULL,

  PRIMARY KEY (`id`),
  UNIQUE KEY `event_game_sl_id` (`game_id`, `sl_event_id`),

  -- Access paths. (game_id, name) serves season sweeps filtered by event
  -- type; (player_id, name) serves per-player metrics -- the two shapes the
  -- metric layer actually issues.
  KEY `event_game_name` (`game_id`, `name`),
  KEY `event_player_name` (`player_id`, `name`),
  KEY `event_game_time` (`game_id`, `game_time`),
  KEY `event_base` (`game_id`, `sl_base_event_id`),
  KEY `event_team` (`team_id`),

  CONSTRAINT `fk_event_game` FOREIGN KEY (`game_id`) REFERENCES `game` (`id`),
  CONSTRAINT `fk_event_team` FOREIGN KEY (`team_id`) REFERENCES `team` (`id`),
  CONSTRAINT `fk_event_player` FOREIGN KEY (`player_id`) REFERENCES `player` (`id`),
  CONSTRAINT `fk_event_possession_team` FOREIGN KEY (`team_in_possession`) REFERENCES `team` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Flags, normalised out of the varchar(255) list. 0.52 flags per event, max 9
-- observed, 64 distinct values -- so this is ~3000 rows per game, not the
-- 70,000 an on-ice table would cost.
CREATE TABLE `flag` (
  `id`   SMALLINT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(40) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `flag_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE `event_flag` (
  `event_id` BIGINT NOT NULL,
  `flag_id`  SMALLINT NOT NULL,
  PRIMARY KEY (`event_id`, `flag_id`),
  -- "every event carrying flag X", e.g. all 1-timers in a season
  KEY `event_flag_by_flag` (`flag_id`, `event_id`),
  CONSTRAINT `fk_event_flag_event` FOREIGN KEY (`event_id`) REFERENCES `event` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_event_flag_flag` FOREIGN KEY (`flag_id`) REFERENCES `flag` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

SET FOREIGN_KEY_CHECKS = 1;
