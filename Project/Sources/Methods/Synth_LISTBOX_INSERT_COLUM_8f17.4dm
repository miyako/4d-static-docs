// overload 0
var $v1 : Variant
LISTBOX INSERT COLUMN FORMULA(*;"synthText";1;"synthText";"synthText";1;"synthText";1;"synthText";$v1)
// overload 0 flag-sweep omit-leading-thru:*
var $v2 : Variant
var $v3 : Variant
LISTBOX INSERT COLUMN FORMULA($v2;1;"synthText";"synthText";1;"synthText";1;"synthText";$v3)
// overload 0 union-sweep headerVar=Integer
var $v4 : Variant
LISTBOX INSERT COLUMN FORMULA(*;"synthText";1;"synthText";"synthText";1;"synthText";1;"synthText";$v4)
// overload 0 union-sweep headerVar=Pointer
var $v5 : Variant
LISTBOX INSERT COLUMN FORMULA(*;"synthText";1;"synthText";"synthText";1;"synthText";Nil;"synthText";$v5)
// overload 0 union-sweep footerVar=Variable
var $v6 : Variant
LISTBOX INSERT COLUMN FORMULA(*;"synthText";1;"synthText";"synthText";1;"synthText";1;"synthText";$v6)
// overload 0 union-sweep footerVar=Pointer
LISTBOX INSERT COLUMN FORMULA(*;"synthText";1;"synthText";"synthText";1;"synthText";1;"synthText";Nil)
