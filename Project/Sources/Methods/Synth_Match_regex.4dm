// overload 0
var $synthResult_0 : Variant
$synthResult_0:=Match regex("synthText";"synthText")
// overload 1
var $v1 : Integer
var $v2 : Integer
var $synthResult_1 : Variant
$synthResult_1:=Match regex("synthText";"synthText";1;$v1;$v2;*)
// overload 2
ARRAY INTEGER($arr3;0)
ARRAY INTEGER($arr4;0)
var $synthResult_2 : Variant
$synthResult_2:=Match regex("synthText";"synthText";1;$arr3;$arr4;*)
