import pyvisa
rm = pyvisa.ResourceManager('@py')
print(rm.list_resources())
