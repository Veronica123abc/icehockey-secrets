An event with name="possession" is a child event hanging off a base event (the
puck event that established the possession: pass, shot, puckprotection,
dumpin, dumpout).

SportLogIQ counts a possession as successful only when BOTH the possession
event and its base event are successful. The possession event's own outcome is
not sufficient -- in game 191848, 1094 possession events are successful but
only 900 of those have a successful base event.

Possession events exist only in the compiled vocabulary.
