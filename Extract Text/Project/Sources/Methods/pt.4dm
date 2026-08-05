//%attributes = {"invisible":true}
var $homeFolder : 4D:C1709.Folder
$homeFolder:=Folder:C1567(fk home folder:K87:24).folder(".GGUF")

var $provider; $model : Text
$provider:="llama.cpp"
$model:="LFM2.5-Embedding-350M"
var $modelFile : 4D:C1709.File
$modelFile:=$homeFolder.file("LiquidAI/LFM2.5-Embedding-350M-Q8_0.gguf")
/*
the tokenizer takes time to load so do it once
*/
cs:C1710.Global.me.loadTokenizer($modelFile)

var $DRYRUN : Boolean
$DRYRUN:=False:C215

var $client : cs:C1710.AIKit.OpenAI
$client:=cs:C1710.AIKit.OpenAI.new({baseURL: "http://127.0.0.1:8080/v1"})
var $params : cs:C1710.AIKit.OpenAIEmbeddingsParameters
$params:=cs:C1710.AIKit.OpenAIEmbeddingsParameters.new({dimensions: 1024})

var $docSrc : 4D:C1709.Folder
$docSrc:=Folder:C1567(Folder:C1567("/PACKAGE/").platformPath; fk platform path:K87:2).parent.folder("mirror/docs")

var $language : Text
$language:="pt"

var $folder : 4D:C1709.Folder
For each ($folder; $docSrc.folder($language).folders())
	
	var $version : Text
	If (["18"; "19"; "20"; "21"; "21-R3"].includes($folder.name))
		$version:=$folder.name
	Else 
		$version:="21-R4"
	End if 
	
	var $files : Collection
	$files:=$folder.files(fk recursive:K87:7).query("extension == :1"; ".html")
	
	var $batch : Object
	var $i; $length : Integer
	$i:=0
	$length:=8
	
	var $inputs : Collection
	$inputs:=$files.slice($i; $i+$length)
	
	var $file : 4D:C1709.File
	
	var $sources : Collection
	$sources:=[]
	
	For each ($file; $inputs)
		
		var $task; $extract : Object
		$task:={file: $file; \
			text_as_tokens: False:C215; \
			tokens_length: 30000; \
			overlap_ratio: 0; \
			unique_values_only: False:C215; \
			pooling_mode: Extract Pooling Mode CLS}
		
		$extract:=Extract(Extract Document HTML; Extract Output Collection; $task)
		
		If ($extract.success)
			
			ASSERT:C1129($extract.input.length=1)
			
			var $input; $anchor : Text
			$input:=$extract.input.first()
			$anchor:="Nesta página\n"
			$input:=Substring:C12($input; Position:C15($anchor; $input; *)+Length:C16($anchor))
			
			$sources.push({input: $input; file: $file})
		End if 
	End for each 
	var $texts : Collection
	$texts:=$sources.extract("input")
	$batch:=$client.embeddings.create($texts; $model; $params)
	If ($batch.success)
		var $embeddings; $source : Object
		For each ($embeddings; $batch.embeddings)
			$source:=$sources.shift()
			$file:=$source.file
			var $path : Text
			$path:=Substring:C12($file.path; Length:C16($docSrc.parent.path))
			var $Doc : cs:C1710.DocEntity
			$Doc:=ds:C1482.Doc.new()
			$Doc.version:=$version
			$Doc.text:=$source.input
			$Doc.embeddings:=$embeddings.embedding
			$Doc.language:=$language
			$Doc.meta:={model: $model; provider: $provider}
			$Doc.URL:="https://developer.4d.com"+$path
			If (Not:C34($DRYRUN))
				$Doc.save()
			End if 
		End for each 
	End if 
	$i+=$length
	$inputs:=$files.slice($i; $i+$length)
End for each 
