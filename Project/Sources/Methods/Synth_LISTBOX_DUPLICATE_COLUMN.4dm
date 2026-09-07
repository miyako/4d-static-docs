// overload 0
ARRAY LONGINT($arr1;0)
var $v2 : Variant
LISTBOX DUPLICATE COLUMN(*;"synthText";1;"synthText";$arr1;"synthText";1;"synthText";$v2)
// overload 0 union-sweep colVariable=Array
ARRAY LONGINT($arr3;0)
var $v4 : Variant
LISTBOX DUPLICATE COLUMN(*;"synthText";1;"synthText";$arr3;"synthText";1;"synthText";$v4)
// overload 0 union-sweep colVariable=Field
var $v5 : Variant
LISTBOX DUPLICATE COLUMN(*;"synthText";1;"synthText";[SynthTable]label;"synthText";1;"synthText";$v5)
// overload 0 union-sweep colVariable=Variable
var $v6 : Variant
var $v7 : Variant
LISTBOX DUPLICATE COLUMN(*;"synthText";1;"synthText";$v6;"synthText";1;"synthText";$v7)
// overload 0 union-sweep colVariable=Pointer
var $v8 : Variant
LISTBOX DUPLICATE COLUMN(*;"synthText";1;"synthText";Nil;"synthText";1;"synthText";$v8)
// overload 0 union-sweep headerVar=Integer
ARRAY LONGINT($arr9;0)
var $v10 : Variant
LISTBOX DUPLICATE COLUMN(*;"synthText";1;"synthText";$arr9;"synthText";1;"synthText";$v10)
// overload 0 union-sweep headerVar=Pointer
ARRAY LONGINT($arr11;0)
var $v12 : Variant
LISTBOX DUPLICATE COLUMN(*;"synthText";1;"synthText";$arr11;"synthText";Nil;"synthText";$v12)
// overload 0 union-sweep footerVar=Variable
ARRAY LONGINT($arr13;0)
var $v14 : Variant
LISTBOX DUPLICATE COLUMN(*;"synthText";1;"synthText";$arr13;"synthText";1;"synthText";$v14)
// overload 0 union-sweep footerVar=Pointer
ARRAY LONGINT($arr15;0)
LISTBOX DUPLICATE COLUMN(*;"synthText";1;"synthText";$arr15;"synthText";1;"synthText";Nil)
// overload 1
var $v16 : Variant
ARRAY LONGINT($arr17;0)
var $v18 : Variant
LISTBOX DUPLICATE COLUMN($v16;1;"synthText";$arr17;"synthText";1;"synthText";$v18)
// overload 1 union-sweep colVariable=Array
var $v19 : Variant
ARRAY LONGINT($arr20;0)
var $v21 : Variant
LISTBOX DUPLICATE COLUMN($v19;1;"synthText";$arr20;"synthText";1;"synthText";$v21)
// overload 1 union-sweep colVariable=Field
var $v22 : Variant
var $v23 : Variant
LISTBOX DUPLICATE COLUMN($v22;1;"synthText";[SynthTable]label;"synthText";1;"synthText";$v23)
// overload 1 union-sweep colVariable=Variable
var $v24 : Variant
var $v25 : Variant
var $v26 : Variant
LISTBOX DUPLICATE COLUMN($v24;1;"synthText";$v25;"synthText";1;"synthText";$v26)
// overload 1 union-sweep colVariable=Pointer
var $v27 : Variant
var $v28 : Variant
LISTBOX DUPLICATE COLUMN($v27;1;"synthText";Nil;"synthText";1;"synthText";$v28)
// overload 1 union-sweep headerVar=Integer
var $v29 : Variant
ARRAY LONGINT($arr30;0)
var $v31 : Variant
LISTBOX DUPLICATE COLUMN($v29;1;"synthText";$arr30;"synthText";1;"synthText";$v31)
// overload 1 union-sweep headerVar=Pointer
var $v32 : Variant
ARRAY LONGINT($arr33;0)
var $v34 : Variant
LISTBOX DUPLICATE COLUMN($v32;1;"synthText";$arr33;"synthText";Nil;"synthText";$v34)
// overload 1 union-sweep footerVar=Variable
var $v35 : Variant
ARRAY LONGINT($arr36;0)
var $v37 : Variant
LISTBOX DUPLICATE COLUMN($v35;1;"synthText";$arr36;"synthText";1;"synthText";$v37)
// overload 1 union-sweep footerVar=Pointer
var $v38 : Variant
ARRAY LONGINT($arr39;0)
LISTBOX DUPLICATE COLUMN($v38;1;"synthText";$arr39;"synthText";1;"synthText";Nil)
