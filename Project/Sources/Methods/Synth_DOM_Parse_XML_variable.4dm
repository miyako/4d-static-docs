// overload 0
var $v1 : Variant
var $synthResult2 : Variant
$synthResult2:=DOM Parse XML variable($v1;True;"synthText")
// overload 0 union-sweep variable=Blob
var $v3 : Variant
var $synthResult4 : Variant
$synthResult4:=DOM Parse XML variable($v3;True;"synthText")
// overload 0 union-sweep variable=Text
var $synthResult5 : Variant
$synthResult5:=DOM Parse XML variable("synthText";True;"synthText")
// overload 1
var $v6 : Variant
var $synthResult7 : Variant
$synthResult7:=DOM Parse XML variable($v6;True;"synthText")
// overload 1 union-sweep variable=Blob
var $v8 : Variant
var $synthResult9 : Variant
$synthResult9:=DOM Parse XML variable($v8;True;"synthText")
// overload 1 union-sweep variable=Text
var $synthResult10 : Variant
$synthResult10:=DOM Parse XML variable("synthText";True;"synthText")
