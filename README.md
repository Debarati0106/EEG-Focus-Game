# EEG-Focus-Game
Developed Frog Focus, an EEG-based focus training game using the Upside Down Labs single-channel EEG kit. The frog survives by maintaining concentration: higher focus lowers the water level, while reduced focus causes it to rise. If the water submerges the frog, the game ends. Built using Python and real-time EEG signal processing.

# Frog Focus – EEG-Based Concentration Monitoring Game
Frog Focus is an interactive brain-computer interface (BCI) game developed using the Upside Down Labs single-channel EEG kit. The game explores the use of real-time brainwave activity to represent a player's concentration level through a simple yet engaging frog survival mechanism.

The core concept revolves around controlling the water level surrounding a frog based on the player's focus. When the player maintains higher concentration, the water level decreases, helping the frog stay safe. When concentration drops, the water level rises, gradually increasing the risk of the frog being submerged. If the water rises beyond a critical level, the game ends. This creates an intuitive visual representation of focus, encouraging players to sustain attention throughout the gameplay.

The system uses a single-channel EEG setup to acquire brain signals from the player. The acquired signals are processed to derive a focus-related measure, which is mapped to changes in the water level in the game environment. This establishes a real-time connection between physiological signals and visual game feedback, allowing the player to observe how changes in measured concentration influence the outcome.

The project combines EEG data acquisition, signal processing, hardware-software integration, and interactive game development to demonstrate a practical application of brain-computer interaction. It also provides an engaging platform for exploring attention monitoring and neurofeedback-based gaming.

Key Features
- Single-channel EEG acquisition using the Upside Down Labs kit.
- Focus-dependent water-level control.
- Real-time visual feedback based on measured concentration.
- Frog survival mechanics with a game-over condition.
- Interactive implementation of EEG-based neurofeedback.

Technologies: Upside Down Labs EEG Kit, Python, EEG Signal Processing, Brain-Computer Interface (BCI), and Game Development.
