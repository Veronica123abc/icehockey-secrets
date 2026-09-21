An event with name='dump' always has one and only one associated event with
name='dumpinentry'. However, a dumpinentry is successful if it is recovered by the 
dumping team. A 'dump' is successful on some other criteria that is not obvious.
It is probably defined by how deep the dumpin went (past last D?)

A 'dumpin' always have type as either 'chip' or 'dump'.

A 'dumpinentry' is decorate with attributes depending on what happens 
inside the offensive zone. It is captured in flags. The flags are also stored as concatenated
strings in type. Flags are: withplayafter, withshotonnet, whithslotshot, withgoal, ..?
A 'dumpin' carries information about the location of the dumping player ('westofdot', ...)
in flags. A dumpinentry does not. 

# dumpinentry as a filtered population

Registered in the catalog as "Dump-in entries". Two groups, and only two —
verified over games 186449 + 186461 + 191848 (209 dump-ins, 209 entries, 1:1,
and all 209 link to their dump-in by base_event_id). Counts are off the FILE
path: 191848 is not ingested in the database, so a database-only check sees
two of the three games:

Result
    Successful      83
    Failed         126

    Exhaustive (83 + 126 = 209). THIS IS THE RECOVERY FACT: a successful
    dumpinentry means the DUMPING team got the puck back. It equals the
    offensive dump-in recoveries exactly — 83 = 83, and per game 25 = 25,
    34 = 34, 24 = 24 — which is what makes "Dump-in entries · Successful" over
    the whole population a true recovery RATE, unlike "Dump-ins · Successful",
    whose criterion is depth, not possession.

With Shot
    With Shot On Net    26
    With Slot Shot      17
    With No Shot       177

    Covers all 209 (union of the two shot items is 32, plus 177). The two
    positive items overlap deliberately, the same convention as shooting's
    'Slot' and controlled entries' 'With Shot'. Type and flags AGREE here,
    unlike controlled entries where the type spells slot shots
    'withshotonnetandslotshot'; the flags are read anyway, for consistency
    with every other module.

Groups deliberately NOT given to this population:

    Technique (rim / cross-ice / soft / straight) — the flags are on the
    dumpinentry too, but they are IDENTICAL to the paired dump-in's on all 209
    pairs, so a group here would be a second name for "Dump-ins · Rim". One
    axis, one place.

    Location — the dumping player's position is on the 'dumpin' only, as noted
    above.

    With Play After — no dumpinentry in the sample carries a withplayafter
    flag, so the group would be a constant. The play-after decoration lives on
    'dumpinrecovery', which has it.

