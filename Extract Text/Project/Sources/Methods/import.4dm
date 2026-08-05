//%attributes = {}
#DECLARE($language : Text)

var $homeFolder : 4D:C1709.Folder
$homeFolder:=Folder:C1567(fk home folder:K87:24).folder(".GGUF")

var $provider; $model; $prefix : Text
$provider:="llama.cpp"
var $modelFile : 4D:C1709.File
var $tokens_length; $dimensions : Integer
var $overlap_ratio : Real

Case of 
	: (True:C214)
		
		$model:="bge-m3"
		$modelFile:=$homeFolder.file("bge-m3/bge-m3-Q8_0.gguf")
		$tokens_length:=8100
		$dimensions:=1024
		$prefix:=""
		$overlap_ratio:=0.09
		
	: (False:C215)
		
		$model:="LFM2.5-Embedding-350M"
		$modelFile:=$homeFolder.file("LiquidAI/LFM2.5-Embedding-350M-Q8_0.gguf")
		$tokens_length:=30000
		$dimensions:=1024
		$prefix:="document: "
		$overlap_ratio:=0
		
End case 

//the tokenizer takes time to load so do it once
cs:C1710.Global.me.loadTokenizer($modelFile)

var $DRYRUN : Boolean
$DRYRUN:=False:C215

var $client : cs:C1710.AIKit.OpenAI
$client:=cs:C1710.AIKit.OpenAI.new({baseURL: "http://127.0.0.1:8080/v1"})
var $params : cs:C1710.AIKit.OpenAIEmbeddingsParameters
$params:=cs:C1710.AIKit.OpenAIEmbeddingsParameters.new({dimensions: $dimensions})

var $docSrc : 4D:C1709.Folder
$docSrc:=Folder:C1567(Folder:C1567("/PACKAGE/").platformPath; fk platform path:K87:2).parent.folder("mirror/docs")

var $folders : Collection
var $folder : 4D:C1709.Folder

If ($language="en")
	$folders:=$docSrc.folders()
Else 
	$folders:=$docSrc.folder($language).folders()
End if 

For each ($folder; $folders)
	
	If ($language="en")
		If (["es"; "fr"; "ja"; "pt"].includes($folder.name))
			continue
		End if 
	End if 
	
	var $version : Text
	If (["18"; "19"; "20"; "21"; "21-R3"].includes($folder.name))
		$version:=$folder.name
	Else 
		$version:="21-R4"
	End if 
	
	var $files : Collection
	$files:=$folder.files(fk recursive:K87:7).query("extension == :1 and not(path in :2)"; ".html"; ["@/commands/theme/@"; "@/commands-legacy/@"])
	
	If ($files.length=0)
		continue
	End if 
	
	var $batch : Object
	var $i; $length : Integer
	$i:=0
	$length:=4
	
	var $inputs : Collection
	$inputs:=$files.slice($i; $i+$length)
	
	var $file : 4D:C1709.File
	
	var $sources : Collection
	$sources:=[]
	
	While ($inputs.length#0)
		For each ($file; $inputs)
			
			If ($file.path="@/commands-legacy/@")
				TRACE:C157
			End if 
			
			var $task; $extract : Object
			$task:={file: $file; \
				text_as_tokens: False:C215; \
				tokens_length: $tokens_length; \
				overlap_ratio: $overlap_ratio; \
				unique_values_only: False:C215; \
				pooling_mode: Extract Pooling Mode CLS}
			
			$extract:=Extract(Extract Document HTML; Extract Output Collection; $task)
			
			If ($extract.success)
				
				var $input; $anchor : Text
				var $first : Boolean
				$first:=True:C214
				For each ($input; $extract.input)
					Case of 
						: ($language="en")
							$anchor:="On this page"
						: ($language="es")
							$anchor:="En esta página"
						: ($language="pt")
							$anchor:="Nesta página"
						: ($language="fr")
							$anchor:="On this page"
						: ($language="ja")
							$anchor:="このページ上で"
					End case 
					If ($first)
						$first:=False:C215
						var $pos : Integer
						$pos:=Position:C15($anchor; $input; *)
						If ($pos=0)
							continue
						End if 
					End if 
					$input:=Substring:C12($input; $pos+Length:C16($anchor)+1)
					$sources.push({input: $prefix+$input; file: $file; text: $input})
				End for each 
			Else 
				TRACE:C157
			End if 
		End for each 
		If ($sources.length#0)
			var $texts : Collection
			$texts:=$sources.extract("input")
			$batch:=$client.embeddings.create($texts; $model; $params)
			If ($batch.success)
				var $embeddings; $source : Object
				For each ($embeddings; $batch.embeddings)
					$source:=$sources.shift()
					var $path : Text
					$path:=Substring:C12($source.file.path; Length:C16($docSrc.parent.path))
					var $Doc : cs:C1710.DocEntity
					$Doc:=ds:C1482.Doc.new()
					$Doc.version:=$version
					$Doc.text:=$source.text
					$Doc.embeddings:=$embeddings.embedding
					$Doc.language:=$language
					$Doc.meta:={model: $model; provider: $provider}
					$Doc.URL:="https://developer.4d.com"+$path
					If (Not:C34($DRYRUN))
						$Doc.save()
					End if 
				End for each 
			Else 
				TRACE:C157
			End if 
		Else 
			
		End if 
		$i+=$length
		$inputs:=$files.slice($i; $i+$length)
	End while 
End for each 