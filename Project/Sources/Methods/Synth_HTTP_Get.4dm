// overload 0
var $v1 : Variant
ARRAY TEXT($arr2;0)
ARRAY TEXT($arr3;0)
var $synthResult4 : Variant
$synthResult4:=HTTP Get("synthText";$v1;$arr2;$arr3;*)
// overload 0 flag-sweep omit-trailing-from:*
var $v5 : Variant
ARRAY TEXT($arr6;0)
ARRAY TEXT($arr7;0)
var $synthResult8 : Variant
$synthResult8:=HTTP Get("synthText";$v5;$arr6;$arr7)
