SET ANSI_NULLS ON;
GO
SET QUOTED_IDENTIFIER ON;
GO

/*
  Converted from MySQL schema dump to Azure SQL Database T-SQL.
  Notes:
  - AUTO_INCREMENT -> IDENTITY(1,1)
  - utf8mb4 varchar columns -> NVARCHAR for safe Unicode support
  - MySQL tinyint flags -> BIT where clearly boolean-like
  - MySQL FLOAT -> REAL
*/

-- Drop child tables first
IF OBJECT_ID(N'dbo.player_on_ice', N'U') IS NOT NULL DROP TABLE dbo.player_on_ice;
GO
IF OBJECT_ID(N'dbo.affiliation', N'U') IS NOT NULL DROP TABLE dbo.affiliation;
GO
IF OBJECT_ID(N'dbo.sl_team_name', N'U') IS NOT NULL DROP TABLE dbo.sl_team_name;
GO
IF OBJECT_ID(N'dbo.event', N'U') IS NOT NULL DROP TABLE dbo.event;
GO
IF OBJECT_ID(N'dbo.participation', N'U') IS NOT NULL DROP TABLE dbo.participation;
GO
IF OBJECT_ID(N'dbo.game', N'U') IS NOT NULL DROP TABLE dbo.[game];
GO
IF OBJECT_ID(N'dbo.player', N'U') IS NOT NULL DROP TABLE dbo.player;
GO
IF OBJECT_ID(N'dbo.team', N'U') IS NOT NULL DROP TABLE dbo.team;
GO
IF OBJECT_ID(N'dbo.league', N'U') IS NOT NULL DROP TABLE dbo.league;
GO
IF OBJECT_ID(N'dbo.test', N'U') IS NOT NULL DROP TABLE dbo.test;
GO

CREATE TABLE dbo.league (
    id INT IDENTITY(1,1) NOT NULL,
    name NVARCHAR(50) NOT NULL,
    sl_id INT NULL,
    sl_name NVARCHAR(50) NULL,
    CONSTRAINT PK_league PRIMARY KEY (id),
    CONSTRAINT UQ_league_name UNIQUE (name)
);
GO

CREATE TABLE dbo.player (
    id INT IDENTITY(1,1) NOT NULL,
    sl_id INT NULL,
    firstName NVARCHAR(255) NULL,
    lastName NVARCHAR(255) NULL,
    CONSTRAINT PK_player PRIMARY KEY (id)
);
GO

CREATE TABLE dbo.team (
    id INT IDENTITY(1,1) NOT NULL,
    name NVARCHAR(50) NOT NULL,
    prefix NVARCHAR(10) NULL,
    suffix NVARCHAR(10) NULL,
    nickname NVARCHAR(50) NULL,
    sl_code NVARCHAR(10) NULL,
    sl_id INT NULL,
    sl_name NVARCHAR(255) NULL,
    CONSTRAINT PK_team PRIMARY KEY (id),
    CONSTRAINT UQ_team_name UNIQUE (name)
);
GO

CREATE TABLE dbo.[game] (
    id INT IDENTITY(1,1) NOT NULL,
    home_team_id INT NULL,
    away_team_id INT NULL,
    [date] DATE NULL,
    sl_game_id INT NULL,
    sl_game_reference_id INT NULL,
    [type] NVARCHAR(10) NULL,
    league_id INT NULL,
    shootout BIT NULL,
    overtime BIT NULL,
    home_team_goals INT NULL,
    away_team_goals INT NULL,
    CONSTRAINT PK_game PRIMARY KEY (id),
    CONSTRAINT UQ_game_matchup UNIQUE (home_team_id, away_team_id, [date]),
    CONSTRAINT FK_game_league_id FOREIGN KEY (league_id) REFERENCES dbo.league(id),
    CONSTRAINT FK_game_team_away_team_id FOREIGN KEY (away_team_id) REFERENCES dbo.team(id),
    CONSTRAINT FK_game_team_home_team_id FOREIGN KEY (home_team_id) REFERENCES dbo.team(id)
);
GO

CREATE INDEX IX_game_league_id ON dbo.[game](league_id);
GO
CREATE INDEX IX_game_away_team_id ON dbo.[game](away_team_id);
GO
CREATE INDEX IX_game_home_team_id ON dbo.[game](home_team_id);
GO

CREATE TABLE dbo.participation (
    id INT IDENTITY(1,1) NOT NULL,
    league_id INT NOT NULL,
    team_id INT NOT NULL,
    season NVARCHAR(255) NOT NULL,
    sl_team_id INT NULL,
    CONSTRAINT PK_participation PRIMARY KEY (id),
    CONSTRAINT UQ_participation_team_league_season UNIQUE (team_id, league_id, season),
    CONSTRAINT FK_participation_league FOREIGN KEY (league_id) REFERENCES dbo.league(id),
    CONSTRAINT FK_participation_team FOREIGN KEY (team_id) REFERENCES dbo.team(id)
);
GO

CREATE INDEX IX_participation_league_team ON dbo.participation(league_id, team_id);
GO

CREATE TABLE dbo.[event] (
    id INT IDENTITY(1,1) NOT NULL,
    sl_id INT NULL,
    period INT NULL,
    period_time REAL NULL,
    game_time REAL NULL,
    possession_id INT NULL,
    team_in_possession INT NULL,
    play_in_possession INT NULL,
    is_possession_event BIT NULL,
    is_defensive_event BIT NULL,
    is_possession_breaking BIT NULL,
    is_last_play_of_possession BIT NULL,
    video_frame INT NULL,
    timecode NVARCHAR(45) NULL,
    shorthand NVARCHAR(255) NULL,
    name NVARCHAR(45) NULL,
    zone NVARCHAR(45) NULL,
    outcome NVARCHAR(45) NULL,
    flags NVARCHAR(255) NULL,
    previous_name NVARCHAR(45) NULL,
    previous_type NVARCHAR(45) NULL,
    previous_outcome NVARCHAR(45) NULL,
    x_coordinate REAL NULL,
    y_coordinate REAL NULL,
    x_adjacent_coordinate REAL NULL,
    y_adjacent_coordinate REAL NULL,
    score_differential INT NULL,
    manpower_situation NVARCHAR(45) NULL,
    team_skaters_on_ice INT NULL,
    play_zone NVARCHAR(45) NULL,
    expected_goals_on_net REAL NULL,
    expected_goals_all_shots REAL NULL,
    game_id INT NULL,
    [type] NVARCHAR(45) NULL,
    player_on_ice NVARCHAR(255) NULL,
    player_id INT NULL,
    team_goalie_id INT NULL,
    opposing_team_goalie_id INT NULL,
    players_on_ice NVARCHAR(255) NULL,
    CONSTRAINT PK_event PRIMARY KEY (id),
    CONSTRAINT UQ_event_game_sl_id UNIQUE (game_id, sl_id),
    CONSTRAINT FK_event_game FOREIGN KEY (game_id) REFERENCES dbo.[game](id)
);
GO

CREATE INDEX IX_event_game_id ON dbo.[event](game_id);
GO
CREATE INDEX IX_event_player_id ON dbo.[event](player_id);
GO
CREATE INDEX IX_event_team_goalie_id ON dbo.[event](team_goalie_id);
GO
CREATE INDEX IX_event_opposing_team_goalie_id ON dbo.[event](opposing_team_goalie_id);
GO

CREATE TABLE dbo.affiliation (
    id INT IDENTITY(1,1) NOT NULL,
    player_id INT NULL,
    team_id INT NULL,
    game_id INT NULL,
    jersey_number INT NULL,
    position NVARCHAR(45) NULL,
    CONSTRAINT PK_affiliation PRIMARY KEY (id),
    CONSTRAINT UQ_affiliation_player_team_game UNIQUE (player_id, team_id, game_id),
    CONSTRAINT FK_affiliation_game FOREIGN KEY (game_id) REFERENCES dbo.[game](id),
    CONSTRAINT FK_affiliation_player FOREIGN KEY (player_id) REFERENCES dbo.player(id),
    CONSTRAINT FK_affiliation_team FOREIGN KEY (team_id) REFERENCES dbo.team(id)
);
GO

CREATE INDEX IX_affiliation_player_id ON dbo.affiliation(player_id);
GO
CREATE INDEX IX_affiliation_team_id ON dbo.affiliation(team_id);
GO
CREATE INDEX IX_affiliation_game_id ON dbo.affiliation(game_id);
GO

CREATE TABLE dbo.player_on_ice (
    id INT IDENTITY(1,1) NOT NULL,
    player_id INT NULL,
    event_id INT NULL,
    CONSTRAINT PK_player_on_ice PRIMARY KEY (id),
    CONSTRAINT UQ_player_on_ice_player_event UNIQUE (player_id, event_id),
    CONSTRAINT FK_player_on_ice_event FOREIGN KEY (event_id) REFERENCES dbo.[event](id),
    CONSTRAINT FK_player_on_ice_player FOREIGN KEY (player_id) REFERENCES dbo.player(id)
);
GO

CREATE INDEX IX_player_on_ice_player_id ON dbo.player_on_ice(player_id);
GO
CREATE INDEX IX_player_on_ice_event_id ON dbo.player_on_ice(event_id);
GO

CREATE TABLE dbo.sl_team_name (
    id INT IDENTITY(1,1) NOT NULL,
    team_id INT NOT NULL,
    sl_team_name NVARCHAR(45) NOT NULL,
    CONSTRAINT PK_sl_team_name PRIMARY KEY (id),
    CONSTRAINT FK_sl_team_name_team FOREIGN KEY (team_id) REFERENCES dbo.team(id)
);
GO

CREATE INDEX IX_sl_team_name_team_id ON dbo.sl_team_name(team_id);
GO

CREATE TABLE dbo.test (
    id INT NULL,
    name NVARCHAR(255) NULL
);
GO