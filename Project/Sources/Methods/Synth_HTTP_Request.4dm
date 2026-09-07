// overload 0
var $v1 : Variant
var $v2 : Variant
ARRAY TEXT($arr3;0)
ARRAY TEXT($arr4;0)
var $synthResult5 : Variant
$synthResult5:=HTTP Request("synthText";"synthText";$v1;$v2;$arr3;$arr4;*)
// overload 0 flag-sweep omit-trailing-from:*
var $v6 : Variant
var $v7 : Variant
ARRAY TEXT($arr8;0)
ARRAY TEXT($arr9;0)
var $synthResult10 : Variant
$synthResult10:=HTTP Request("synthText";"synthText";$v6;$v7;$arr8;$arr9)
