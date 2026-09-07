// overload 0
var $synthResult1 : Variant
$synthResult1:=Get external data path("synthText")
// overload 0 union-sweep aField=Text
var $synthResult2 : Variant
$synthResult2:=Get external data path("synthText")
// overload 0 union-sweep aField=Blob
var $v3 : Variant
var $synthResult4 : Variant
$synthResult4:=Get external data path($v3)
// overload 0 union-sweep aField=Picture
var $v5 : Picture
var $synthResult6 : Variant
$synthResult6:=Get external data path($v5)
