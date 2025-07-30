import pyvisa

rm = pyvisa.ResourceManager('@py')

try:
    scope = rm.open_resource("USB0::0x1AB1::0x04CE::?*::INSTR")
    scope.timeout = 5000
    idn = scope.query("*IDN?")
    print("✅ Connected:", idn)
except Exception as e:
    print("❌ Could not connect via USB:", e)
