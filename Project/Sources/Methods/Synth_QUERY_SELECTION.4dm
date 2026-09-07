// overload 0
QUERY SELECTION([SynthTable];"synthAny";*)
// overload 0 flag-sweep omit-trailing-from:*
QUERY SELECTION([SynthTable];"synthAny")
// overload 1
QUERY SELECTION("synthAny";*)
// overload 1 flag-sweep omit-trailing-from:*
QUERY SELECTION("synthAny")
// overload 2
QUERY SELECTION([SynthTable];[SynthTable]label;"synthText";"synthAny";*)
// overload 2 flag-sweep omit-trailing-from:*
QUERY SELECTION([SynthTable];[SynthTable]label;"synthText";"synthAny")
