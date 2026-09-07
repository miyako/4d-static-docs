// overload 0
ARRAY TEXT($arr1;0)
ARRAY TEXT($arr2;0)
METHOD GET COMMENTS($arr1;$arr2;*)
// overload 0 flag-sweep omit-trailing-from:*
ARRAY TEXT($arr3;0)
ARRAY TEXT($arr4;0)
METHOD GET COMMENTS($arr3;$arr4)
// overload 0 union-sweep path=Text
ARRAY TEXT($arr5;0)
METHOD GET COMMENTS("synthText";$arr5;*)
// overload 0 union-sweep path=Text array
ARRAY TEXT($arr6;0)
ARRAY TEXT($arr7;0)
METHOD GET COMMENTS($arr6;$arr7;*)
// overload 0 union-sweep comments=Text
ARRAY TEXT($arr8;0)
var $v9 : Text
METHOD GET COMMENTS($arr8;$v9;*)
// overload 0 union-sweep comments=Text array
ARRAY TEXT($arr10;0)
ARRAY TEXT($arr11;0)
METHOD GET COMMENTS($arr10;$arr11;*)
