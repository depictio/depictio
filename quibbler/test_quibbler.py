from pyquibbler import initialize_quibbler, iquib

initialize_quibbler()
import matplotlib.pyplot as plt

x = iquib(0.5)
y = 1 - x
plt.plot([0, 1], [1, 0], "-")
plt.plot([0, x, x], [y, y, 0], "--", marker="D")
plt.title(x, fontsize=20)
plt.show()
