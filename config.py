INTERVALL_BILD = 2
INTERVALL_SCPI = 4
WAV_POINTS = 1000   #when set to 1000, no problems should be expected on most scopes.

BLACKLISTED_COMMANDS = [
    ":SYSTem:UPTime?",
    ":SYSTem:TEMPerature?",
    ":SYSTem:OPTions?",
    ":TIMebase:HREFerence?",
    ":ACQuire:MODE?",
    #":ACQuire:TYPE?",
    #":TRIGger:HOLDoff?",
    ":WAVeform:YINCrement?",
    ":WAVeform:YORigin?",
    ":WAVeform:YREFerence?",

    # MATH probe is unsupported on MSO5000 → blacklist exact forms used by our code
    ":MATH1:PROB?",
    ":MATH2:PROB?",
    ":MATH3:PROB?",
    ":MATH4:PROB?",
    # (optional belt-and-suspenders if any code ever used the spelled form)
    # ":MATH1:PROBe?", ":MATH2:PROBe?", ":MATH3:PROBe?", ":MATH4:PROBe?",
]
