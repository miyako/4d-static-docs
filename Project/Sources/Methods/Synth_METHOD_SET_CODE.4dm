// overload 0
ARRAY TEXT($arr1;0)
ARRAY TEXT($arr2;0)
METHOD SET CODE($arr1;$arr2;*)
// overload 0 flag-sweep omit-trailing-from:*
ARRAY TEXT($arr3;0)
ARRAY TEXT($arr4;0)
METHOD SET CODE($arr3;$arr4)
// overload 0 union-sweep path=Text
ARRAY TEXT($arr5;0)
METHOD SET CODE("synthText";$arr5;*)
// overload 0 union-sweep path=Text array
ARRAY TEXT($arr6;0)
ARRAY TEXT($arr7;0)
METHOD SET CODE($arr6;$arr7;*)
// overload 0 union-sweep code=Text
ARRAY TEXT($arr8;0)
METHOD SET CODE($arr8;"synthText";*)
// overload 0 union-sweep code=Text array
ARRAY TEXT($arr9;0)
ARRAY TEXT($arr10;0)
METHOD SET CODE($arr9;$arr10;*)
