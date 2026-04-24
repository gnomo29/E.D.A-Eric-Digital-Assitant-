' Ejecuta Iniciar_EDA.bat sin mostrar ventana de CMD
Dim shell, fso, carpetaBase, comando
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

carpetaBase = fso.GetParentFolderName(WScript.ScriptFullName)
comando = "cmd /c """ & carpetaBase & "\Iniciar_EDA.bat"""

' 0 = oculto, False = no esperar a que termine
shell.Run comando, 0, False

Set fso = Nothing
Set shell = Nothing
