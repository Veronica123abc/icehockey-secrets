-- MySQL dump 10.13  Distrib 8.0.36, for Linux (x86_64)
--
-- Host: 127.0.0.1    Database: hockeystats_ver3
-- ------------------------------------------------------
-- Server version	8.0.42-0ubuntu0.20.04.1

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `affiliation`
--

DROP TABLE IF EXISTS `affiliation`;
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
) ENGINE=InnoDB AUTO_INCREMENT=226812 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `affiliation`
--

LOCK TABLES `affiliation` WRITE;
/*!40000 ALTER TABLE `affiliation` DISABLE KEYS */;
/*!40000 ALTER TABLE `affiliation` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `event`
--

DROP TABLE IF EXISTS `event`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `event` (
  `id` int NOT NULL AUTO_INCREMENT,
  `sl_id` int DEFAULT NULL,
  `period` int DEFAULT NULL,
  `period_time` float DEFAULT NULL,
  `game_time` float DEFAULT NULL,
  `current_possession` int DEFAULT NULL,
  `team_in_possession` varchar(255) DEFAULT NULL,
  `team_id_in_possession` int DEFAULT NULL,
  `opposing_team_id_in_possession` int DEFAULT NULL,
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
  `team_goalie_on_ice_ref` varchar(255) DEFAULT NULL,
  `opposing_team_goalie_on_ice_ref` varchar(255) DEFAULT NULL,
  `team_goalie_on_ice_id` int DEFAULT NULL,
  `opposing_team_goalie_on_ice_id` int DEFAULT NULL,
  `play_zone` varchar(45) DEFAULT NULL,
  `play_section` varchar(5) DEFAULT NULL,
  `game_id` int DEFAULT NULL,
  `type` varchar(45) DEFAULT NULL,
  `team` varchar(45) DEFAULT NULL,
  `player_jersey` varchar(5) DEFAULT NULL,
  `player_id` int DEFAULT NULL,
  `player_position` varchar(5) DEFAULT NULL,
  `player_first_name` varchar(45) DEFAULT NULL,
  `player_last_name` varchar(45) DEFAULT NULL,
  `player_reference_id` varchar(10) DEFAULT NULL,
  `expected_goals_on_net` float DEFAULT NULL,
  `expected_goals_all_shots` float DEFAULT NULL,
  `expected_goals_on_net_grade` varchar(10) DEFAULT NULL,
  `expected_goals_all_shots_grade` varchar(10) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `id_UNIQUE` (`id`),
  UNIQUE KEY `game_event_UNIQUE` (`game_id`,`sl_id`),
  KEY `fk_event_game_idx` (`game_id`),
  KEY `fk_event_player_idx` (`player_id`),
  KEY `fk_event_team_goalie_id_idx` (`team_goalie_on_ice_id`),
  KEY `fk_event_opposing_team_goalie_id_idx` (`opposing_team_goalie_on_ice_id`),
  CONSTRAINT `event_game` FOREIGN KEY (`game_id`) REFERENCES `game` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=27271086 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `event`
--

LOCK TABLES `event` WRITE;
/*!40000 ALTER TABLE `event` DISABLE KEYS */;
/*!40000 ALTER TABLE `event` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `game`
--

DROP TABLE IF EXISTS `game`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `game` (
  `id` int NOT NULL AUTO_INCREMENT,
  `home_team_id` int DEFAULT NULL,
  `away_team_id` int DEFAULT NULL,
  `date` date DEFAULT NULL,
  `sl_game_id` int DEFAULT NULL,
  `sl_game_reference_id` int DEFAULT NULL,
  `type` varchar(10) DEFAULT NULL,
  `league_id` int DEFAULT NULL,
  `shootout` tinyint DEFAULT NULL,
  `overtime` tinyint DEFAULT NULL,
  `home_team_goals` int DEFAULT NULL,
  `away_team_goals` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `game_matchup` (`home_team_id`,`away_team_id`,`date`),
  UNIQUE KEY `game_sl_game_id_unique` (`sl_game_id`) USING BTREE,
  KEY `fk_game_league_id_idx` (`league_id`),
  KEY `fk_game_team_away_team_id_idx` (`away_team_id`),
  KEY `fk_game_away_team_id_idx` (`away_team_id`),
  CONSTRAINT `game_away_team_team_id` FOREIGN KEY (`away_team_id`) REFERENCES `team` (`id`),
  CONSTRAINT `game_home_team_id` FOREIGN KEY (`home_team_id`) REFERENCES `team` (`id`),
  CONSTRAINT `game_league_id` FOREIGN KEY (`league_id`) REFERENCES `league` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=9073 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `game`
--

LOCK TABLES `game` WRITE;
/*!40000 ALTER TABLE `game` DISABLE KEYS */;
/*!40000 ALTER TABLE `game` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `league`
--

DROP TABLE IF EXISTS `league`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `league` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(50) NOT NULL,
  `sl_id` int DEFAULT NULL,
  `sl_name` varchar(50) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `league_sl_id` (`sl_id`)
) ENGINE=InnoDB AUTO_INCREMENT=218 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `league`
--

LOCK TABLES `league` WRITE;
/*!40000 ALTER TABLE `league` DISABLE KEYS */;
/*!40000 ALTER TABLE `league` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `participation`
--

DROP TABLE IF EXISTS `participation`;
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
) ENGINE=InnoDB AUTO_INCREMENT=223 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `participation`
--

LOCK TABLES `participation` WRITE;
/*!40000 ALTER TABLE `participation` DISABLE KEYS */;
/*!40000 ALTER TABLE `participation` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `player`
--

DROP TABLE IF EXISTS `player`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `player` (
  `id` int NOT NULL AUTO_INCREMENT,
  `sl_id` int DEFAULT NULL,
  `first_name` varchar(255) DEFAULT NULL,
  `last_name` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `player_sl_id` (`sl_id`)
) ENGINE=InnoDB AUTO_INCREMENT=2768 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `player`
--

LOCK TABLES `player` WRITE;
/*!40000 ALTER TABLE `player` DISABLE KEYS */;
/*!40000 ALTER TABLE `player` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `team`
--

DROP TABLE IF EXISTS `team`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `team` (
  `id` int NOT NULL AUTO_INCREMENT,
  `league_id` int DEFAULT NULL,
  `location` varchar(255) DEFAULT NULL,
  `name` varchar(255) NOT NULL,
  `logo_source` varchar(255) DEFAULT NULL,
  `shorthand` varchar(255) DEFAULT NULL,
  `display_name` varchar(255) DEFAULT NULL,
  `default_venue_id` int DEFAULT NULL,
  `past_team_id` int DEFAULT NULL,
  `created_on` datetime DEFAULT NULL,
  `updated_on` datetime DEFAULT NULL,
  `sl_id` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `name_location` (`name`,`location`),
  UNIQUE KEY `sl_id_UNIQUE` (`sl_id`)
) ENGINE=InnoDB AUTO_INCREMENT=101 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `team`
--

LOCK TABLES `team` WRITE;
/*!40000 ALTER TABLE `team` DISABLE KEYS */;
/*!40000 ALTER TABLE `team` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `toi_shifts`
--

DROP TABLE IF EXISTS `toi_shifts`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `toi_shifts` (
  `id` int NOT NULL AUTO_INCREMENT,
  `player_id` int NOT NULL,
  `game_id` int NOT NULL,
  `in` float NOT NULL,
  `out` float DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `player_game_in_out` (`player_id`,`game_id`,`in`,`out`),
  KEY `fk_player_idx` (`player_id`),
  KEY `fk_game_idx` (`game_id`),
  CONSTRAINT `fk_toi_shift_game` FOREIGN KEY (`game_id`) REFERENCES `game` (`id`),
  CONSTRAINT `fk_toi_shift_player` FOREIGN KEY (`player_id`) REFERENCES `player` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `toi_shifts`
--

LOCK TABLES `toi_shifts` WRITE;
/*!40000 ALTER TABLE `toi_shifts` DISABLE KEYS */;
/*!40000 ALTER TABLE `toi_shifts` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-04-04 18:03:35
