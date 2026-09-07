// overload 0
ARRAY TEXT($arr1;0)
METHOD SET ATTRIBUTES($arr1;New object;*)
// overload 0 flag-sweep omit-trailing-from:*
ARRAY TEXT($arr2;0)
METHOD SET ATTRIBUTES($arr2;New object)
// overload 0 union-sweep path=Text
METHOD SET ATTRIBUTES("synthText";New object;*)
// overload 0 union-sweep path=Text array
ARRAY TEXT($arr3;0)
METHOD SET ATTRIBUTES($arr3;New object;*)
// overload 0 union-sweep attributes=Object
ARRAY TEXT($arr4;0)
METHOD SET ATTRIBUTES($arr4;New object;*)
// overload 0 union-sweep attributes=Object array
ARRAY TEXT($arr5;0)
ARRAY OBJECT($arr6;0)
METHOD SET ATTRIBUTES($arr5;$arr6;*)
