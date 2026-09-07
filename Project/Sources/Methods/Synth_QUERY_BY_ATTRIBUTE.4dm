// overload 0
QUERY BY ATTRIBUTE([SynthTable];&;[SynthTable]label;"myFirstAttribute.mySecondAttribute";"synthText";1;*)
// overload 0 flag-sweep omit-leading-thru:conjOp
QUERY BY ATTRIBUTE([SynthTable]label;"myFirstAttribute.mySecondAttribute";"synthText";1;*)
// overload 0 flag-sweep omit-trailing-from:*
QUERY BY ATTRIBUTE([SynthTable];&;[SynthTable]label;"myFirstAttribute.mySecondAttribute";"synthText";1)
