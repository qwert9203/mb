from microbit import *
import utime as time
from ssd1306 import initialize, clear_oled, draw_screen, screen
from ssd1306_px import set_px
import speech

hb_monitor = pin0

# information about the navigation hierarchy
navigation = {
    "Menu": ["o", "Menu", "Record", "Profile", "Recordings"],
    "Profile": ["o", "Profile", "Age: {age}", "Sex: {sex}", ""],
    "Recordings": ["o", "Recordings", "1: {rec1}", "2: {rec2}", "3: {rec3}"],
    "Record": ["g", "Bpm: {bpm}", "", "", ""],
    "Age: {age}": ["s", "Age: ", "", " < {age} >", "", "age", range(120)],
    "Sex: {sex}": ["s", "Sex:", "", " < {sex} >", "", "sex", ("F", "M", "n/a")],
    "Watch": ["l", "Watch", "1: {rec1}", "2: {rec2}", "3: {rec3}"],
    "1: {rec1}": ["g", "R:{rec1}", "", "", "", 0],
    "2: {rec2}": ["g", "R:{rec2}", "", "", "", 1],
    "3: {rec3}": ["g", "R:{rec3}", "", "", "", 2]
}

# stores variables accessed by menus
info = {
    "age": 18,
    "sex": "n/a",
    "rec1": "empty",  # name for recording 1
    "rec2": "empty",  # name for recording 2
    "rec3": "empty",  # name for recording 3
    "bpm": 0,
    "a": 18, # metadata for age
    "s": 2, # metadata for sex
    "showheart": False
}

# stores 3 recordings each with 256 ints (bytearray = nope)
recordings = [bytes(256) for _ in range(3)]



# 0: nothing, 1: a, 2: b, 3: a+b
def get_response():
    return button_a.was_pressed() + button_b.was_pressed() * 2

# format the string bc fstring being weird
def form(x:str):
    start, end = x.find("{"), x.find("}")
    s = x.replace(x[start:end+1], str(info[x[start+1:end]])) if start > 0 and end > 0 else x
    return (s+" "*11)[:11]

# restricts x between a and b or returns oob instead if enabled and x is out of range
def clamp(a, b, x, oob=None):
    if oob is None:
        return min(max(x, a), b)
    else:
        return oob if x < a or x > b else x

# prints a character on the oled screen, a stripped down version of add_text()
def set_chr(x, y, text):
    for c in range(0, 5):
        col = 0
        for r in range(1, 6):
            p = Image(text).get_pixel(c, r - 1)
            col = col | (1 << r) if (p != 0) else col
        ind = x * 10 + y * 128 + c * 2 + 1
        screen[ind], screen[ind + 1] = col, col

# this needs to be fixed lol
# gets information about the bpm and whether it is an onbeat or not
def get_info(cur, l, bpm_calc_num=10):
    if l:
        bpm_time = 1
        thres = clamp(3, 20, sum(cur) / l)
        total = 0
        for i, x in enumerate(reversed(cur)):
            if not total % 2 and x > thres:
                total += 1
            elif total % 2 and x < thres:
                total += 1
            if total == bpm_calc_num * 2:
                bpm_time = i
        return cur[-1] > thres, clamp(10, 220, int(bpm_calc_num * 480 / max(1, bpm_time)), oob=-1)
    else:
        return False, -1

# updates titles of recordings after saving a record
def update_rec_titles():
    for i in range(3):
        bpm = (get_info(recordings[i], 256))[1]
        info["rec" + str(i+1)] = str(bpm) + "bpm" if bpm != -1 else "empty"

# INIT

selected = 0  # current selected menu item
stack = ["Menu"] # menu stack
needs_update, scr_c = True, True # stuff to make the laggiest functions run only when needed
mode = "o" # behavior mode (option, selection, graph)
current_rec = [0 for x in range(256)]  # current recording
disp = [list(" "*48), list(" "*48)]  # display cache (text) , [0] stores the next frame, [1] stores the frame on the oled
g_stage = 0  # global iterator for rendering the graph
warning = False

# read from files
try:
    with open("data.txt", "rb") as data_text:
        i = data_text.read()
        if len(i) == 768:
            recordings = [i[:256], i[256:512], i[512:]]
            update_rec_titles()
        else:
            print("recording corrupted", len(i), i)
except OSError:
    with open("data.txt", "wb") as data_text:
        data_text.write(bytes(768))

try:
    with open("settings.txt") as settings_text:
        j = settings_text.read()
        info["s"], info["a"] = int(j[0]), int(j[1:])
        info["sex"] = navigation["Sex: {sex}"][6][info["s"]]
        info["age"] = info["a"]
except OSError:
    with open("settings.txt", "wt") as settings_text:
        settings_text.write("218")

# oled boilerplate
initialize()
clear_oled()

# LOOP
while True:
    # timer start
    t = time.ticks_ms()

    # checks buttons for response
    r = get_response()
    if r in (1, 2):
        if mode == "o":
            selected = (selected - 3 + 2*r) % sum([1 if x != "" else 0 for x in navigation[stack[-1]][1:5]])
            needs_update = True
        elif mode == "s":
            ctx = navigation[stack[-1]] # the variable to be changed (age or sex)
            upd = (info[ctx[5][0]] - 3 + 2*r) % len(ctx[6]) # index of the updated variable
            info[ctx[5]], info[ctx[5][0]] = ctx[6][upd], upd  # updates the variable, index
            needs_update = True
    elif r == 3:  # enter
        if selected != 0:
            stack.append(navigation[stack[-1]][selected + 1])
            mode = navigation[stack[-1]][0]
            needs_update = True
            selected = 0
        elif len(stack) > 1:  # if not at root of menu, exit
            if mode == "g":
                clear_oled()
                disp[1] = list(" "*48)
                g_stage = 0
                info["showheart"] = False
                bpm = 0
                if warning:
                    speech.say("warning")
                    warning = False
            if mode == "s":
                with open("settings.txt", "wt") as j:
                    j.write(str(info["s"])+str(info["a"]))
            stack.pop()
            mode = navigation[stack[-1]][0]
            needs_update = True

    # SAVE RECORDING
    elif sum(current_rec) and stack[-1] != "Record":
        # reset memory
        recordings = [bytes(current_rec)] + recordings[:2]
        current_rec = [0 for x in range(256)]
        # save file
        with open("data.txt", "wb") as data_text:
            data_text.write(recordings[0]+recordings[1]+recordings[2])

        update_rec_titles()

    # GRAPH
    if mode == "g": # for when exiting the recording and the mode hasn't changed yet
        g_stage = g_stage + 1
        if stack[-1] == "Record":
            v = hb_monitor.read_analog()
            current_rec = current_rec[1:] + [v // 43]
            info["showheart"], info["bpm"] = get_info(current_rec, min(g_stage, 256))
            oled_signal = current_rec[-1]
        else:
            rec = recordings[navigation[stack[-1]][5]]
            info["showheart"], info["bpm"] = get_info(rec[g_stage % 256:] + rec[:g_stage % 256], 256)
            oled_signal = rec[(g_stage - 1) % 256]
        for y in range(oled_signal):
            set_px(g_stage % 64 ,31-y,1, draw=0)
        for y in range(96):
            set_px((g_stage + y//24 + 1) % 64, 31-y%24, 0, draw=0)

        # LED health warning
        warning=False
        sex = info["sex"]
        age = info["age"]
        bpm = info["bpm"]

        if sex=="M":
            if age<=35:
                if bpm<=49 or bpm>=82:
                    warning=True
            elif age<=45:
                if bpm<=50 or bpm>=83:
                    warning=True
            elif age<=55:
                if bpm<=50 or bpm>=84:
                    warning=True
            elif age<=65:
                if bpm<=51 or bpm>=82:
                    warning=True
            else:
                if bpm<=50 or bpm>=80:
                    warning=True
        elif sex=="F":
            if age<=25:
                if bpm<=49 or bpm>=82:
                    warning=True
            if age<=35:
                if bpm<=54 or bpm>=83:
                    warning=True
            elif age<=45:
                if bpm<=54 or bpm>=85:
                    warning=True
            elif age<=55:
                if bpm<=54 or bpm>=84:
                    warning=True
            elif age<=65:
                if bpm<=54 or bpm>=84:
                    warning=True
            else:
                if bpm<=54 or bpm>=84:
                    warning=True

        needs_update = True
        scr_c = True

    # UPDATE TEXT ON OLED
    if needs_update:
        disp[0] = list("".join([">"+form(x) if i == selected else " "+form(x) for i, x in enumerate(navigation[stack[-1]][1:5])]))
        if mode == "g" and stack[-1] != "Record":
            bpmstr = str(info["bpm"])
            for i, x in enumerate(bpmstr):
                disp[0][9+i] = x
        needs_update = False
        for i in range(48):
            if disp[0][i] != disp[1][i]:
                scr_c = True
                disp[1][i] = disp[0][i]
                set_chr(i % 12, i // 12, disp[1][i])

    # UPDATE OLED
    if scr_c:
        draw_screen()
        scr_c = False

    # SHOW HEART+LED (WIP)
    if info["showheart"]:
        display.show(Image.HEART)
    else:
        display.clear()
    pin1.write_analog(warning * 512)


    # TIMER
    t2 = time.ticks_ms() - t
    if t2 > 125:
        print("A tick took " +str(t2) + " ms in " + stack[-1] + "!")
    sleep(125 - t2)


