// overload 0
var $v1 : Variant
var $v2 : Variant
var $synthResult_0 : Variant
$synthResult_0:=ZIP Create archive($v1;$v2)
// overload 1
var $v3 : Variant
var $v4 : Variant
var $synthResult_1 : Variant
$synthResult_1:=ZIP Create archive($v3;$v4;1)
// overload 2
var $v5 : Variant
var $synthResult_2 : Variant
$synthResult_2:=ZIP Create archive(New object;$v5)
