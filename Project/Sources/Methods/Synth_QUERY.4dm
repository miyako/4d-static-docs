// overload 0
QUERY([SynthTable];[SynthTable]label="synthAny";*)
// overload 0 flag-sweep omit-trailing-from:*
QUERY([SynthTable];[SynthTable]label="synthAny")
// overload 1
QUERY([SynthTable]label="synthAny";*)
// overload 1 flag-sweep omit-trailing-from:*
QUERY([SynthTable]label="synthAny")
// overload 2
QUERY([SynthTable];[SynthTable]label;"=";"synthAny";*)
// overload 2 flag-sweep omit-trailing-from:*
QUERY([SynthTable];[SynthTable]label;"=";"synthAny")
