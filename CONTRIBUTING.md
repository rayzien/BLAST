# Contributing to BLAST

Thank you for your interest in contributing to BLAST! As an open-source project, we welcome contributions from everyone.

## Code of Conduct
Please be respectful and considerate of other contributors. We maintain a friendly, welcoming environment for developers of all skill levels.

## How to Contribute

1. **Fork the Repository**: Create a personal fork of the repository on GitHub.
2. **Clone your Fork**:
   ```bash
   git clone https://github.com/<your-username>/BLAST.git
   cd BLAST
   ```
3. **Create a Feature Branch**:
   ```bash
   git checkout -b feature/my-new-feature
   ```
4. **Make Your Changes**:
   - Write clean, documented Python code.
   - Maintain the architectural rule: zero emojis in system logs.
   - Follow PEP 8 style conventions.
5. **Run the Test Suite**:
   ```bash
   python3 -m unittest discover tests
   ```
   Ensure all existing tests pass before submitting your PR.
6. **Submit a Pull Request**:
   - Push your branch to your fork.
   - Open a pull request against `main` on the upstream repository.
   - Provide a concise description of your changes and motivation.

## License
By contributing to BLAST, you agree that your contributions will be licensed under the MIT License.
