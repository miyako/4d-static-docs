// overload 0
var $synthResult1 : Variant
$synthResult1:=Match regex("synthText";"synthText")
// overload 1
var $v2 : Integer
var $v3 : Integer
var $synthResult4 : Variant
$synthResult4:=Match regex("synthText";"synthText";1;$v2;$v3;*)
// overload 2
ARRAY INTEGER($arr5;0)
ARRAY INTEGER($arr6;0)
var $synthResult7 : Variant
$synthResult7:=Match regex("synthText";"synthText";1;$arr5;$arr6;*)
