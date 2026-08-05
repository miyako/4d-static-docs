//%attributes = {}
var $all : cs:C1710.DocSelection
$all:=ds:C1482.Doc.all()

var $jsonL : Collection
$jsonL:=[]

var $file : 4D:C1709.File
$file:=Folder:C1567(fk desktop folder:K87:19).file("data.jsonl")

var $Doc : cs:C1710.DocEntity
For each ($Doc; $all)
	var $json : Object
	$json:={url: $Doc.URL; \
		text: $Doc.text; \
		embedding: $Doc.embeddings.toCollection(); \
		language: $Doc.language; \
		version: $Doc.version}
	$jsonL.push(JSON Stringify:C1217($json))
End for each 

$file.setText($jsonL.join("\n"))