'********************************************************************************************/
'* File Name       : StopRecording.vbs
'* Created Date  : 2024-10-15 01:50:30
'* Author            : Hmily
'* GitHub            : http://github.com/sjwayrhz
'* Description     : This script is designed to terminate the process of live recording
'********************************************************************************************/

Dim objWMIService, colProcesses, objProcess
Dim intResponse
strComputer = "."
On Error Resume Next
intResponse = MsgBox("ȷ��Ҫ�������к�ֱ̨��¼�ƽ�����", vbYesNo + vbQuestion, "ȷ�Ͻ�������")

If intResponse = vbYes Then
    Set objWMIService = GetObject("winmgmts:\\" & strComputer & "\root\cimv2")
    If Err.Number <> 0 Then
        Err.Clear
    End If

    Set colProcesses = objWMIService.ExecQuery("Select * from Win32_Process Where Name = 'ffmpeg.exe'")
    Set colProcesses2 = objWMIService.ExecQuery("Select * from Win32_Process Where Name = 'pythonw.exe'")
    Set colProcesses3 = objWMIService.ExecQuery("Select * from Win32_Process Where Name = 'DouyinLiveRecorder.exe'")
    If Err.Number <> 0 Then
        Err.Clear
    End If

    If Not objWMIService Is Nothing And Not colProcesses Is Nothing  And Not colProcesses2 Is Nothing Then
        If colProcesses2.Count = 0 And colProcesses3.Count = 0 Then
            MsgBox "û���ҵ�¼�Ƴ���Ľ���", vbExclamation, "��ʾ��Ϣ"
            WScript.Quit(1)
        Else
            For Each objProcess in colProcesses
                objProcess.Terminate()
                If Err.Number <> 0 Then
                    objShell.Run "taskkill /f /im " & objProcess.Name, 0, True
                    Err.Clear
                End If                
            Next
        End If
    Else
        objShell.Run "taskkill /f /im " & objProcess.Name, 0, True
    End If
    MsgBox "�ѳɹ���������¼��ֱ���Ľ��̣�" & vbCrLf & "�رմ˴���30����Զ�ֹͣ¼�Ƴ���", vbInformation, "��ʾ��Ϣ"

    WScript.Sleep 10000
    If colProcesses3.Count <> 0 Then
        Set colProcesses_ = colProcesses3
    Else
        Set colProcesses_ = colProcesses2
    End If
    For Each objProcess in colProcesses_
        objProcess.Terminate()
        If Err.Number <> 0 Then
            objShell.Run "taskkill /f /im " & objProcess.Name, 0, True
            Err.Clear
        End If         
    Next
Else
    MsgBox "��ȡ������¼�Ʋ���", vbExclamation, "��ʾ��Ϣ"
End If

On Error GoTo 0
Set objWMIService = Nothing
Set colProcesses = Nothing
Set colProcesses2 = Nothing
Set colProcesses3 = Nothing
Set objProcess = Nothing
Set objShell = Nothing