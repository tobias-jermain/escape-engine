-- Opens a Terminal window with large text running `escape menu`,
-- then puts the text size back when the menu closes.
on run argv
	set escapeBin to item 1 of argv
	set cmd to "clear; " & quoted form of escapeBin & " menu; exit"
	set wasRunning to application "Terminal" is running
	tell application "Terminal"
		activate
		if wasRunning then
			set t to do script cmd
		else
			set t to do script cmd in window 1
		end if
		set s to current settings of t
		set oldSize to font size of s
		set font size of s to 20
		try
			set number of columns of t to 100
			set number of rows of t to 40
		end try
		try
			repeat while busy of t
				delay 1
			end repeat
		end try
		set font size of s to oldSize
	end tell
end run
