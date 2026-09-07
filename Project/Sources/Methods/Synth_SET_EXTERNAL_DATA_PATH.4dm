// overload 0
SET EXTERNAL DATA PATH("synthText";"synthText")
// overload 0 union-sweep aField=Text
SET EXTERNAL DATA PATH("synthText";"synthText")
// overload 0 union-sweep aField=Blob
var $v1 : Variant
SET EXTERNAL DATA PATH($v1;"synthText")
// overload 0 union-sweep aField=Picture
var $v2 : Picture
SET EXTERNAL DATA PATH($v2;"synthText")
// overload 0 union-sweep path=Text
SET EXTERNAL DATA PATH("synthText";"synthText")
// overload 0 union-sweep path=Integer
SET EXTERNAL DATA PATH("synthText";1)
