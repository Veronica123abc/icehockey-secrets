
/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `affiliation` (
  `id` int NOT NULL AUTO_INCREMENT,
  `player_id` int DEFAULT NULL,
  `team_id` int DEFAULT NULL,
  `game_id` int DEFAULT NULL,
  `jersey_number` int DEFAULT NULL,
  `position` varchar(2) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `id_UNIQUE` (`id`),
  UNIQUE KEY `player_team_game_idx` (`player_id`,`team_id`,`game_id`),
  KEY `fk_affiliation_player_id_idx` (`player_id`),
  KEY `fk_affiliation_team_id_idx` (`team_id`),
  KEY `fk_affiliation_game_id_idx` (`game_id`),
  CONSTRAINT `affiliation_game_id` FOREIGN KEY (`game_id`) REFERENCES `game` (`id`),
  CONSTRAINT `affiliation_player_id` FOREIGN KEY (`player_id`) REFERENCES `player` (`id`),
  CONSTRAINT `affiliation_team_id` FOREIGN KEY (`team_id`) REFERENCES `team` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=240003 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `compiled_event` (
  `id` int NOT NULL,
  `base_event_id` int DEFAULT NULL,
  `sl_event_id` varchar(45) DEFAULT NULL,
  `sl_base_event_id` varchar(45) DEFAULT NULL,
  `game_id` int DEFAULT NULL,
  `x_adj_coord` float DEFAULT NULL,
  `y_adj_coord` float DEFAULT NULL,
  `zone` varchar(2) DEFAULT NULL,
  `period` int DEFAULT NULL,
  `period_time` float DEFAULT NULL,
  `game_time` float DEFAULT NULL,
  `team_id` int DEFAULT NULL,
  `player_id` int DEFAULT NULL,
  `shorthand` varchar(255) DEFAULT NULL,
  `name` varchar(45) DEFAULT NULL,
  `type` varchar(255) DEFAULT NULL,
  `outcome` varchar(45) DEFAULT NULL,
  `flags` varchar(255) DEFAULT NULL,
  `current_possession` int DEFAULT NULL,
  `current_play_in_possession` int DEFAULT NULL,
  `team_in_possession` int DEFAULT NULL,
  `manpowersituation` varchar(45) DEFAULT NULL,
  `team_skaters_on_ice` int DEFAULT NULL,
  `opposing_team_skaters_on_ice` int DEFAULT NULL,
  `play_section` varchar(45) DEFAULT NULL,
  `expected_goals_all_shots` float DEFAULT '0',
  `expected_goals_on_net` float DEFAULT '0',
  `expected_goals_on_net_grade` char(1) DEFAULT NULL,
  `expected_goals_all_shots_grade` char(1) DEFAULT NULL,
  `team_forwards_on_ice_refs` varchar(255) DEFAULT NULL,
  `opposing_team_defencemen_on_ice_refs` varchar(255) DEFAULT NULL,
  `team_defencemen_on_ice_refs` varchar(255) DEFAULT NULL,
  `opposing_team_forwards_on_ice_refs` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `idnew_table_UNIQUE` (`id`),
  KEY `fk_compiled_event_1_idx` (`game_id`),
  KEY `fk_compiled_event_2_idx` (`player_id`),
  CONSTRAINT `fk_compiled_event_1` FOREIGN KEY (`game_id`) REFERENCES `game` (`id`) ON UPDATE RESTRICT,
  CONSTRAINT `fk_compiled_event_2` FOREIGN KEY (`player_id`) REFERENCES `player` (`id`) ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `event` (
  `id` int NOT NULL AUTO_INCREMENT,
  `sl_id` int DEFAULT NULL,
  `period` int DEFAULT NULL,
  `period_time` float DEFAULT NULL,
  `game_time` float DEFAULT NULL,
  `current_possession` int DEFAULT NULL,
  `team_in_possession` int DEFAULT NULL,
  `current_play_in_possession` int DEFAULT NULL,
  `is_possession_event` tinyint DEFAULT NULL,
  `is_defensive_event` tinyint DEFAULT NULL,
  `is_possession_breaking` tinyint DEFAULT NULL,
  `is_last_play_of_possession` tinyint DEFAULT NULL,
  `frame` int DEFAULT NULL,
  `timecode` varchar(45) DEFAULT NULL,
  `shorthand` varchar(255) DEFAULT NULL,
  `name` varchar(45) DEFAULT NULL,
  `zone` varchar(45) DEFAULT NULL,
  `outcome` varchar(45) DEFAULT NULL,
  `flags` varchar(255) DEFAULT NULL,
  `previous_name` varchar(45) DEFAULT NULL,
  `previous_type` varchar(45) DEFAULT NULL,
  `previous_outcome` varchar(45) DEFAULT NULL,
  `x_coord` float DEFAULT NULL,
  `y_coord` float DEFAULT NULL,
  `x_adj_coord` float DEFAULT NULL,
  `y_adj_coord` float DEFAULT NULL,
  `score_differential` int DEFAULT NULL,
  `manpower_situation` varchar(45) DEFAULT NULL,
  `team_skaters_on_ice` int DEFAULT NULL,
  `team_forwards_on_ice_refs` varchar(255) DEFAULT NULL,
  `team_defencemen_on_ice_refs` varchar(255) DEFAULT NULL,
  `opposing_team_forwards_on_ice_refs` varchar(255) DEFAULT NULL,
  `opposing_team_defencemen_on_ice_refs` varchar(255) DEFAULT NULL,
  `team_goalie_on_ice_ref` int DEFAULT NULL,
  `opposing_team_goalie_on_ice_ref` int DEFAULT NULL,
  `play_zone` varchar(45) DEFAULT NULL,
  `play_section` varchar(45) DEFAULT NULL,
  `game_id` int DEFAULT NULL,
  `type` varchar(45) DEFAULT NULL,
  `team` int DEFAULT NULL,
  `player_reference_id` int DEFAULT NULL,
  `expected_goals_on_net` float DEFAULT NULL,
  `expected_goals_all_shots` float DEFAULT NULL,
  `expected_goals_on_net_grade` varchar(10) DEFAULT NULL,
  `expected_goals_all_shots_grade` varchar(10) DEFAULT NULL,
  `opposing_team_skaters_on_ice` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `id_UNIQUE` (`id`),
  UNIQUE KEY `game_event_UNIQUE` (`game_id`,`sl_id`),
  UNIQUE KEY `game_pos_posId` (`game_id`,`current_play_in_possession`,`current_possession`),
  KEY `fk_event_game_idx` (`game_id`),
  KEY `fk_event_player_idx` (`player_reference_id`),
  CONSTRAINT `event_game` FOREIGN KEY (`game_id`) REFERENCES `game` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=28306145 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `game` (
  `id` int NOT NULL AUTO_INCREMENT,
  `sl_id` int DEFAULT NULL,
  `home_team_id` int DEFAULT NULL,
  `away_team_id` int DEFAULT NULL,
  `league_id` int DEFAULT NULL,
  `season` varchar(45) DEFAULT NULL,
  `stage` varchar(45) DEFAULT NULL,
  `scheduled_time` datetime DEFAULT NULL,
  `scheduled_venue_time` datetime DEFAULT NULL,
  `venue_id` int DEFAULT NULL,
  `event_status` varchar(45) DEFAULT NULL,
  `sl_reference_id` int DEFAULT NULL,
  `sl_reference_name` varchar(45) DEFAULT NULL,
  `home_team_goals` int DEFAULT NULL,
  `away_team_goals` int DEFAULT NULL,
  `home_shootout_score` int DEFAULT NULL,
  `last_metrics_full_process_time` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `game_matchup` (`home_team_id`,`away_team_id`,`scheduled_time`),
  UNIQUE KEY `sl_id_unique` (`sl_id`) USING BTREE,
  KEY `fk_game_league_id_idx` (`league_id`),
  KEY `fk_game_team_away_team_id_idx` (`away_team_id`),
  KEY `fk_game_away_team_id_idx` (`away_team_id`),
  CONSTRAINT `game_away_team_team_id` FOREIGN KEY (`away_team_id`) REFERENCES `team` (`id`),
  CONSTRAINT `game_home_team_id` FOREIGN KEY (`home_team_id`) REFERENCES `team` (`id`),
  CONSTRAINT `game_league_id` FOREIGN KEY (`league_id`) REFERENCES `league` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=11104 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `league` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(50) NOT NULL,
  `sl_id` int DEFAULT NULL,
  `sl_name` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `league_sl_id` (`sl_id`)
) ENGINE=InnoDB AUTO_INCREMENT=498 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `participation` (
  `id` int NOT NULL AUTO_INCREMENT,
  `league_id` int NOT NULL,
  `team_id` int NOT NULL,
  `season` varchar(255) NOT NULL,
  `sl_team_id` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `team_id` (`team_id`,`league_id`,`season`),
  KEY `participation_league` (`league_id`),
  CONSTRAINT `participation_league` FOREIGN KEY (`league_id`) REFERENCES `league` (`id`),
  CONSTRAINT `participation_team` FOREIGN KEY (`team_id`) REFERENCES `team` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=387 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `player` (
  `id` int NOT NULL AUTO_INCREMENT,
  `sl_id` int DEFAULT NULL,
  `first_name` varchar(255) DEFAULT NULL,
  `last_name` varchar(255) DEFAULT NULL,
  `display_first_name` varchar(45) DEFAULT NULL,
  `display_last_name` varchar(45) DEFAULT NULL,
  `birthdate` datetime DEFAULT NULL,
  `birth_city` varchar(45) DEFAULT NULL,
  `birth_province` varchar(45) DEFAULT NULL,
  `birth_country` varchar(45) DEFAULT NULL,
  `nationality` varchar(45) DEFAULT NULL,
  `picture_source` varchar(45) DEFAULT NULL,
  `current_salary` int DEFAULT NULL,
  `free_agent_status` varchar(45) DEFAULT NULL,
  `future_free_agent_status` varchar(45) DEFAULT NULL,
  `future_free_agent_year` varchar(45) DEFAULT NULL,
  `primary_position` varchar(6) DEFAULT NULL,
  `weight` int DEFAULT NULL,
  `height` int DEFAULT NULL,
  `laterality` varchar(4) DEFAULT NULL,
  `updated_on` varchar(45) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `player_sl_id` (`sl_id`)
) ENGINE=InnoDB AUTO_INCREMENT=19741 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `shift` (
  `id` int NOT NULL AUTO_INCREMENT,
  `player_id` int NOT NULL,
  `game_id` int NOT NULL,
  `in_time` float NOT NULL,
  `out_time` float DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `player_game_in_out` (`player_id`,`game_id`,`in_time`,`out_time`),
  KEY `fk_player_idx` (`player_id`),
  KEY `fk_game_idx` (`game_id`),
  CONSTRAINT `fk_toi_shift_game` FOREIGN KEY (`game_id`) REFERENCES `game` (`id`),
  CONSTRAINT `fk_toi_shift_player` FOREIGN KEY (`player_id`) REFERENCES `player` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=263750 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `team` (
  `id` int NOT NULL AUTO_INCREMENT,
  `league_id` int DEFAULT NULL,
  `name` varchar(255) NOT NULL,
  `location` varchar(255) DEFAULT NULL,
  `logo_source` varchar(255) DEFAULT NULL,
  `shorthand` varchar(255) DEFAULT NULL,
  `display_name` varchar(255) DEFAULT NULL,
  `default_venue_id` int DEFAULT NULL,
  `past_team_id` int DEFAULT NULL,
  `created_on` datetime DEFAULT NULL,
  `updated_on` datetime DEFAULT NULL,
  `sl_id` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `sl_id_UNIQUE` (`sl_id`)
) ENGINE=InnoDB AUTO_INCREMENT=17866 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

