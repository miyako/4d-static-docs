// overload 0
ARRAY TEXT($arr1;0)
ARRAY TEXT($arr2;0)
METHOD GET CODE($arr1;$arr2;1;*)
// overload 0 flag-sweep omit-trailing-from:*
ARRAY TEXT($arr3;0)
ARRAY TEXT($arr4;0)
METHOD GET CODE($arr3;$arr4;1)
// overload 0 union-sweep path=Text
ARRAY TEXT($arr5;0)
METHOD GET CODE("synthText";$arr5;1;*)
// overload 0 union-sweep path=Text array
ARRAY TEXT($arr6;0)
ARRAY TEXT($arr7;0)
METHOD GET CODE($arr6;$arr7;1;*)
// overload 0 union-sweep code=Text
ARRAY TEXT($arr8;0)
var $v9 : Text
METHOD GET CODE($arr8;$v9;1;*)
// overload 0 union-sweep code=Text array
ARRAY TEXT($arr10;0)
ARRAY TEXT($arr11;0)
METHOD GET CODE($arr10;$arr11;1;*)
