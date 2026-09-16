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

