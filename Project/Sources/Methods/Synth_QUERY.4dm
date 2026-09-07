// overload 0
QUERY([SynthTable];"synthAny";*)
// overload 0 flag-sweep omit-trailing-from:*
QUERY([SynthTable];"synthAny")
// overload 1
QUERY("synthAny";*)
// overload 1 flag-sweep omit-trailing-from:*
QUERY("synthAny")
// overload 2
QUERY([SynthTable];[SynthTable]label;"synthText";"synthAny";*)
// overload 2 flag-sweep omit-trailing-from:*
QUERY([SynthTable];[SynthTable]label;"synthText";"synthAny")
