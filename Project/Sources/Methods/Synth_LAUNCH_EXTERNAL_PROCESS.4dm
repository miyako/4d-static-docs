// overload 0
var $v1 : Text
var $v2 : Text
var $v3 : Integer
LAUNCH EXTERNAL PROCESS("synthText";"synthText";$v1;$v2;$v3)
// overload 0 union-sweep inputStream=Text
var $v4 : Text
var $v5 : Text
var $v6 : Integer
LAUNCH EXTERNAL PROCESS("synthText";"synthText";$v4;$v5;$v6)
// overload 0 union-sweep inputStream=Blob
var $v7 : Variant
var $v8 : Text
var $v9 : Text
var $v10 : Integer
LAUNCH EXTERNAL PROCESS("synthText";$v7;$v8;$v9;$v10)
// overload 0 union-sweep outputStream=Text
var $v11 : Text
var $v12 : Text
var $v13 : Integer
LAUNCH EXTERNAL PROCESS("synthText";"synthText";$v11;$v12;$v13)
// overload 0 union-sweep outputStream=Blob
var $v14 : Variant
var $v15 : Text
var $v16 : Integer
LAUNCH EXTERNAL PROCESS("synthText";"synthText";$v14;$v15;$v16)
// overload 0 union-sweep errorStream=Text
var $v17 : Text
var $v18 : Text
var $v19 : Integer
LAUNCH EXTERNAL PROCESS("synthText";"synthText";$v17;$v18;$v19)
// overload 0 union-sweep errorStream=Blob
var $v20 : Text
var $v21 : Variant
var $v22 : Integer
LAUNCH EXTERNAL PROCESS("synthText";"synthText";$v20;$v21;$v22)
