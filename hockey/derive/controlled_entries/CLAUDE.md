In playsequence_compiled.json, the events representing an OZ entry defined as follows:


Controlled entry attempts into OZ
   name="controlledentry"
   outcome="successful"
   
Successful Controlled entry into OZ
   name="controlledentry"
   outcome="successful"
   withplayafter in flags

Carry attempts into OZ:
   name="controlledentry"
   "carry" is a substring of type

Pass into OZ:
   name="controlledentry"
   outcome="successful"
   "pass" is a substring of type
   
# Notes
A controlled entry by PASS can fail if the reception fails.

A controlled entry by CARRY is ALWAYS successful. However, successful carries
seem to be defined by a successful play after.

An entry where the carrying player immediately shots does NOT (it seems like)
get registered as an entry. Overridden by shot or slotshot??

