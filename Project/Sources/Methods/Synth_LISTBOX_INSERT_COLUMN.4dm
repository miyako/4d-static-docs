// overload 0
ARRAY LONGINT($arr1;0)
var $v2 : Variant
LISTBOX INSERT COLUMN(*;"synthText";1;"synthText";$arr1;"synthText";1;"synthText";$v2)
// overload 0 flag-sweep omit-leading-thru:*
var $v3 : Variant
ARRAY LONGINT($arr4;0)
var $v5 : Variant
LISTBOX INSERT COLUMN($v3;1;"synthText";$arr4;"synthText";1;"synthText";$v5)
// overload 0 union-sweep colVariable=Array
ARRAY LONGINT($arr6;0)
var $v7 : Variant
LISTBOX INSERT COLUMN(*;"synthText";1;"synthText";$arr6;"synthText";1;"synthText";$v7)
// overload 0 union-sweep colVariable=Field
var $v8 : Variant
LISTBOX INSERT COLUMN(*;"synthText";1;"synthText";[SynthTable]label;"synthText";1;"synthText";$v8)
// overload 0 union-sweep colVariable=Variable
var $v9 : Variant
var $v10 : Variant
LISTBOX INSERT COLUMN(*;"synthText";1;"synthText";$v9;"synthText";1;"synthText";$v10)
// overload 0 union-sweep colVariable=Pointer
var $v11 : Variant
LISTBOX INSERT COLUMN(*;"synthText";1;"synthText";Nil;"synthText";1;"synthText";$v11)
// overload 0 union-sweep headerVar=Integer
ARRAY LONGINT($arr12;0)
var $v13 : Variant
LISTBOX INSERT COLUMN(*;"synthText";1;"synthText";$arr12;"synthText";1;"synthText";$v13)
// overload 0 union-sweep headerVar=Pointer
ARRAY LONGINT($arr14;0)
var $v15 : Variant
LISTBOX INSERT COLUMN(*;"synthText";1;"synthText";$arr14;"synthText";Nil;"synthText";$v15)
// overload 0 union-sweep footerVar=Variable
ARRAY LONGINT($arr16;0)
var $v17 : Variant
LISTBOX INSERT COLUMN(*;"synthText";1;"synthText";$arr16;"synthText";1;"synthText";$v17)
// overload 0 union-sweep footerVar=Pointer
ARRAY LONGINT($arr18;0)
LISTBOX INSERT COLUMN(*;"synthText";1;"synthText";$arr18;"synthText";1;"synthText";Nil)
