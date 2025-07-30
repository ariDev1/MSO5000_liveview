import pyvisa

rm = pyvisa.ResourceManager('@py')
resources = rm.list_resources()
print("Resources:", resources)

for res in resources:
    if "USB" in res:
        try:
            print(f"🔌 Trying {res} ...")
            instr = rm.open_resource(res)
            idn = instr.query("*IDN?")
            print(f"✅ IDN: {idn}")
        except Exception as e:
            print(f"❌ Failed to connect to {res}: {e}")
