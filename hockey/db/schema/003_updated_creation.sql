create table league
(
    id      int identity
        constraint PK_league
            primary key,
    name    nvarchar(50) not null
        constraint UQ_league_name
            unique,
    sl_id   int,
    sl_name nvarchar(50)
)
go

create table competition
(
    id        int identity
        constraint competition_pk
            primary key,
    league_id int
        constraint competition_league_id_fk
            references league,
    season    varchar(50) default 'none'    not null,
    stage     varchar(50) default 'regular' not null
)
go

create table player
(
    id        int identity
        constraint PK_player
            primary key,
    sl_id     int,
    firstName nvarchar(255),
    lastName  nvarchar(255)
)
go

create table team
(
    id       int identity
        constraint PK_team
            primary key,
    name     nvarchar(50) not null
        constraint UQ_team_name
            unique,
    prefix   nvarchar(10),
    suffix   nvarchar(10),
    nickname nvarchar(50),
    sl_code  nvarchar(10),
    sl_id    int,
    sl_name  nvarchar(255)
)
go

create table game
(
    id                   int identity
        constraint PK_game
            primary key,
    home_team_id         int
        constraint FK_game_team_home_team_id
            references team,
    away_team_id         int
        constraint FK_game_team_away_team_id
            references team,
    date                 date,
    sl_game_id           int,
    sl_game_reference_id int,
    type                 nvarchar(10),
    league_id            int
        constraint FK_game_league_id
            references league,
    shootout             bit,
    overtime             bit,
    home_team_goals      int,
    away_team_goals      int,
    constraint UQ_game_matchup
        unique (home_team_id, away_team_id, date)
)
go

create table affiliation
(
    id            int identity
        constraint PK_affiliation
            primary key,
    player_id     int
        constraint FK_affiliation_player
            references player,
    team_id       int
        constraint FK_affiliation_team
            references team,
    game_id       int
        constraint FK_affiliation_game
            references game,
    jersey_number int,
    position      nvarchar(45),
    constraint UQ_affiliation_player_team_game
        unique (player_id, team_id, game_id)
)
go

create index IX_affiliation_player_id
    on affiliation (player_id)
go

create index IX_affiliation_team_id
    on affiliation (team_id)
go

create index IX_affiliation_game_id
    on affiliation (game_id)
go

create table event
(
    id                                   int identity
        constraint PK_event
            primary key,
    sl_id                                int,
    period_number                        int,
    period_time                          real,
    game_time                            real,
    current_possession                   int,
    team_in_possession                   int,
    current_play_in_possession           int,
    is_possession_event                  bit,
    is_defensive_event                   bit,
    is_possession_breaking               bit,
    is_last_play_of_possession           bit,
    video_frame                          int,
    timecode                             nvarchar(45),
    shorthand                            nvarchar(255),
    name                                 nvarchar(45),
    zone                                 nvarchar(45),
    outcome                              nvarchar(45),
    flags                                nvarchar(255),
    previous_name                        nvarchar(45),
    previous_type                        nvarchar(45),
    previous_outcome                     nvarchar(45),
    x_coord                              real,
    y_coord                              real,
    x_adj_coord                          real,
    y_adj_coord                          real,
    score_differential                   int,
    manpower_situation                   nvarchar(45),
    team_skaters_on_ice                  int,
    play_zone                            nvarchar(45),
    expected_goals_on_net                real,
    expected_goals_all_shots             real,
    game_id                              int
        constraint FK_event_game
            references game,
    type                                 nvarchar(45),
    player_on_ice                        nvarchar(255),
    player_id                            int,
    team_goalie_id                       int,
    opposing_team_goalie_id              int,
    players_on_ice                       nvarchar(255),
    expected_goals_on_net_grade          nvarchar(10),
    expected_goals_all_shots_grade       nvarchar(10),
    team_goalie_on_ice_ref               varchar(50),
    opposing_team_goalie_on_ice_ref      int,
    team_forwards_on_ice_refs            varchar(50),
    opposing_team_forwards_on_ice_refs   varchar(50),
    team_defencemen_on_ice_refs          varchar(50),
    opposing_team_defencemen_on_ice_refs varchar(50),
    constraint UQ_event_game_sl_id
        unique (game_id, sl_id)
)
go

create index IX_event_game_id
    on event (game_id)
go

create index IX_event_player_id
    on event (player_id)
go

create index IX_event_team_goalie_id
    on event (team_goalie_id)
go

create index IX_event_opposing_team_goalie_id
    on event (opposing_team_goalie_id)
go

create index IX_game_league_id
    on game (league_id)
go

create index IX_game_away_team_id
    on game (away_team_id)
go

create index IX_game_home_team_id
    on game (home_team_id)
go

create table participation
(
    id         int identity
        constraint PK_participation
            primary key,
    league_id  int           not null
        constraint FK_participation_league
            references league,
    team_id    int           not null
        constraint FK_participation_team
            references team,
    season     nvarchar(255) not null,
    sl_team_id int,
    constraint UQ_participation_team_league_season
        unique (team_id, league_id, season)
)
go

create index IX_participation_league_team
    on participation (league_id, team_id)
go

create table player_on_ice
(
    id        int identity
        constraint PK_player_on_ice
            primary key,
    player_id int
        constraint FK_player_on_ice_player
            references player,
    event_id  int
        constraint FK_player_on_ice_event
            references event,
    constraint UQ_player_on_ice_player_event
        unique (player_id, event_id)
)
go

create index IX_player_on_ice_player_id
    on player_on_ice (player_id)
go

create index IX_player_on_ice_event_id
    on player_on_ice (event_id)
go

create table sl_team_name
(
    id           int identity
        constraint PK_sl_team_name
            primary key,
    team_id      int          not null
        constraint FK_sl_team_name_team
            references team,
    sl_team_name nvarchar(45) not null
)
go

create index IX_sl_team_name_team_id
    on sl_team_name (team_id)
go

create table test
(
    id   int,
    name nvarchar(255)
)
go

