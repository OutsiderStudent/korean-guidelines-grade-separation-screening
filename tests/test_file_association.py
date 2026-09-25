import unittest
from pathlib import Path

from interchange_review.file_association import open_command, startup_project_path


class FileAssociationTest(unittest.TestCase):
    def test_startup_project_path_accepts_korean_spaces_and_uppercase_extension(self) -> None:
        path = startup_project_path(["--ignored", r"C:\검토 자료\서울 교차로.IGR3"])
        self.assertEqual(path, Path(r"C:\검토 자료\서울 교차로.IGR3"))

    def test_startup_project_path_ignores_non_project_arguments(self) -> None:
        self.assertIsNone(startup_project_path(["--safe", "교차로.json"]))

    def test_open_command_quotes_executable_and_project_argument(self) -> None:
        executable = Path(r"C:\Program Files\K-GSS\K-GSS_v3.8.0.exe")
        self.assertEqual(open_command(executable), f'"{executable.resolve()}" "%1"')


if __name__ == "__main__":
    unittest.main()
