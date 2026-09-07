// overload 0
QUERY SELECTION([SynthTable];[SynthTable]label="synthAny";*)
// overload 0 flag-sweep omit-trailing-from:*
QUERY SELECTION([SynthTable];[SynthTable]label="synthAny")
// overload 1
QUERY SELECTION([SynthTable]label="synthAny";*)
// overload 1 flag-sweep omit-trailing-from:*
QUERY SELECTION([SynthTable]label="synthAny")
// overload 2
QUERY SELECTION([SynthTable];[SynthTable]label;"=";"synthAny";*)
// overload 2 flag-sweep omit-trailing-from:*
QUERY SELECTION([SynthTable];[SynthTable]label;"=";"synthAny")
