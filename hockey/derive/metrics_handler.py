#!/usr/bin/python
from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable

from hockey.model.events import Event
from hockey.data_collection.sportlogiq_api import SportlogiqApi
from hockey.config.settings import Settings
from hockey.catalog import DataCatalog
from hockey.data_collection.sportlogiq_api import download_complete_games
from hockey.io.raw_game import RawGame
from hockey.normalize.build_game import build_game
from hockey.model.game import Game
settings = Settings.from_env(project_root=Path(__file__).resolve().parent)
from hockey.derive.controlled_entries.metrics import oz_carry, oz_pass
from hockey.derive.dumpins.metrics import dumpin, dumpin_recovery, dumpin_entry, chipin
from hockey.derive.DZExits.metrics import controlled_exits, dz_carry_outs, exit_pass, dumpouts, opposition_dumpin_recoveries
from hockey.derive.playmaking.metrics import expected_goals_all_shots, expected_goals_on_net, ogp_passes_otr, ogp_passes_1timer, ogp_passes_to_slot, ogp, scoring_chances
from hockey.derive.shooting.metrics_v2 import all_shots

class metricsHandler(object):

    def __init__(self, raw_game: RawGame):
        self.raw_game = raw_game
        self.game = build_game(raw_game)
        self.team_id = None
        self.settings = settings

    def set_team_id(self, team_id: int):
        self.team_id = team_id

    def reset_team_id(self):
        self.team_id = None

    # CONTROLLED ENTRIES
    def oz_carry(self):
        return self.oz_carry()


    def oz_pass(self):
        return oz_pass(self.game)


    # DUMPINS
    def dumpin(self):
        return dumpin(self.game)

    def chipin(self):
        return chipin(self.game)

    def dumpin_recovery(self):
        return dumpin_recovery(self.game)

    def dumpin_entry(self):
        return dumpin_entry(self.game)

    def opposition_dumpin_recoveries(self):
        return opposition_dumpin_recoveries(self.game)


    # DZ EXITS
    def controlled_exits(self):
        return 33

    def controlled_exits(self):
        return controlled_exits(self.game)

    def dz_carry_outs(self):
        return dz_carry_outs(self.game)

    def exit_pass(self):
        return exit_pass(self.game)

    def dumpouts(self):
        return dumpouts(self.game)


    #PLAYMAKING
    # def expected_goals_all_shots(self):
    #     return expected_goals_all_shots(self.game, self.raw_game)
    #
    # def expected_goals_on_net(self, game, raw_game):
    #     return expected_goals_on_net(game, raw_game)

    def scoring_chances(self):
        return scoring_chances(self.game, self.raw_game)

    def ogp_passes_otr(self):
        return ogp_passes_otr(self.game)

    def ogp_passes_1timer(self):
        return ogp_passes_1timer(self.game)

    def ogp_passes_to_slot(self):
        return ogp_passes_to_slot(self.game)

    def ogp(self):
        return ogp(self.game)

    def shots(self):
        return

    def _filter_team(self, events, team_id):
        team_events = [e for e in events if e["team_id"] == str(team_id)]
        return team_events

    def _xG_category(self, events: Iterable, category: str):
        return [e for e in events if e['grade'] == category]


    def print_all(self):
        game = build_game(raw)
        team_ids = [game.info.home_team.id, game.info.away_team.id]
        for team_id in team_ids:
            all_expected_goals = self.scoring_chances()
            all_expected_goals = self._filter_team(all_expected_goals, team_id)
            print(f"Chances for team {team_id}: {len(all_expected_goals)}")
            print(f"A Chances: {len(self._xG_category(all_expected_goals, 'A'))}")
            print(f"B Chances: {len(self._xG_category(all_expected_goals, 'B'))}")
            print(f"C Chances: {len(self._xG_category(all_expected_goals, 'C'))}")

            ogp_otr = self.ogp_passes_otr()
            ogp_otr = self._filter_team(ogp_otr, team_id)
            ogp_slot = self.ogp_passes_to_slot()
            ogp_slot = self._filter_team(ogp_slot, team_id)
            ogp_1t = self.ogp_passes_1timer()
            ogp_1t = self._filter_team(ogp_1t, team_id)

            print(f"OGP Pass Off the Rush: {len(ogp_otr)}")
            print(f"OGP Pass to 1-timer: {len(ogp_1t)}")
            print(f"OGP Pass to Slot: {len(ogp_slot)}")


            # all_expected_goals_A = _xG_category(all_expected_goals, 'A')
            # all_expected_goals_B = _xG_category(all_expected_goals, 'B')


if __name__ == "__main__":
    GAME_ID = 191848
    raw = RawGame(game_id=GAME_ID, root_dir=settings.data_root_dir, playsequence_source="playsequence_compiled")
    mh = metricsHandler(raw)
    mh.print_all()