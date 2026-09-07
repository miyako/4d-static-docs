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
var $v8 : Pointer
var $v9 : Variant
LISTBOX DUPLICATE COLUMN(*;"synthText";1;"synthText";$v8;"synthText";1;"synthText";$v9)
// overload 0 union-sweep headerVar=Integer
ARRAY LONGINT($arr10;0)
var $v11 : Variant
LISTBOX DUPLICATE COLUMN(*;"synthText";1;"synthText";$arr10;"synthText";1;"synthText";$v11)
// overload 0 union-sweep headerVar=Pointer
ARRAY LONGINT($arr12;0)
var $v13 : Pointer
var $v14 : Variant
LISTBOX DUPLICATE COLUMN(*;"synthText";1;"synthText";$arr12;"synthText";$v13;"synthText";$v14)
// overload 0 union-sweep footerVar=Variable
ARRAY LONGINT($arr15;0)
var $v16 : Variant
LISTBOX DUPLICATE COLUMN(*;"synthText";1;"synthText";$arr15;"synthText";1;"synthText";$v16)
// overload 0 union-sweep footerVar=Pointer
ARRAY LONGINT($arr17;0)
var $v18 : Pointer
LISTBOX DUPLICATE COLUMN(*;"synthText";1;"synthText";$arr17;"synthText";1;"synthText";$v18)
// overload 1
var $v19 : Variant
ARRAY LONGINT($arr20;0)
var $v21 : Variant
LISTBOX DUPLICATE COLUMN($v19;1;"synthText";$arr20;"synthText";1;"synthText";$v21)
// overload 1 union-sweep colVariable=Array
var $v22 : Variant
ARRAY LONGINT($arr23;0)
var $v24 : Variant
LISTBOX DUPLICATE COLUMN($v22;1;"synthText";$arr23;"synthText";1;"synthText";$v24)
// overload 1 union-sweep colVariable=Field
var $v25 : Variant
var $v26 : Variant
LISTBOX DUPLICATE COLUMN($v25;1;"synthText";[SynthTable]label;"synthText";1;"synthText";$v26)
// overload 1 union-sweep colVariable=Variable
var $v27 : Variant
var $v28 : Variant
var $v29 : Variant
LISTBOX DUPLICATE COLUMN($v27;1;"synthText";$v28;"synthText";1;"synthText";$v29)
// overload 1 union-sweep colVariable=Pointer
var $v30 : Variant
var $v31 : Pointer
var $v32 : Variant
LISTBOX DUPLICATE COLUMN($v30;1;"synthText";$v31;"synthText";1;"synthText";$v32)
// overload 1 union-sweep headerVar=Integer
var $v33 : Variant
ARRAY LONGINT($arr34;0)
var $v35 : Variant
LISTBOX DUPLICATE COLUMN($v33;1;"synthText";$arr34;"synthText";1;"synthText";$v35)
// overload 1 union-sweep headerVar=Pointer
var $v36 : Variant
ARRAY LONGINT($arr37;0)
var $v38 : Pointer
var $v39 : Variant
LISTBOX DUPLICATE COLUMN($v36;1;"synthText";$arr37;"synthText";$v38;"synthText";$v39)
// overload 1 union-sweep footerVar=Variable
var $v40 : Variant
ARRAY LONGINT($arr41;0)
var $v42 : Variant
LISTBOX DUPLICATE COLUMN($v40;1;"synthText";$arr41;"synthText";1;"synthText";$v42)
// overload 1 union-sweep footerVar=Pointer
var $v43 : Variant
ARRAY LONGINT($arr44;0)
var $v45 : Pointer
LISTBOX DUPLICATE COLUMN($v43;1;"synthText";$arr44;"synthText";1;"synthText";$v45)
