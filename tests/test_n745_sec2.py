"""Тест-гварды наряда #745 SEC-2: образ офиса получает security-обновления.

Текстовые гварды в стиле test_n717_sec1.py (инфраструктура — Dockerfile /
ci.yml / entrypoint.sh — юнит-тестом не исполняется, инварианты наряда
закрепляются по содержимому файлов):

- A.1: в Dockerfile после `apt-get update` идёт `apt-get upgrade -y
  --no-install-recommends` (тот же RUN-слой — update и upgrade не
  разнесены); версия пакета НЕ закреплена в install (запрет наряда);
- A.1 CI-гейт: в ci.yml job docker-build есть шаг Verify libssl3t64 с
  `dpkg --compare-versions ... ge` и константой минимума
  3.0.13-0ubuntu3.16 (USN-8847-1); шаг условен как сборка
  (available == 'yes');
- A.2: в entrypoint.sh строка `security: libssl3t64=… openssl=…`
  (dpkg-версия пакета, fallback unknown — бут не роняет).

Мутационная проверка (AGENTS.md): удаление upgrade-строки из Dockerfile,
смена `ge` на `lt` в гейте или удаление security-строки из entrypoint
валит соответствующий тест.
"""
import os
import re
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

DOCKERFILE = os.path.join(REPO_ROOT, "Dockerfile")
CI = os.path.join(REPO_ROOT, ".github", "workflows", "ci.yml")
ENTRYPOINT = os.path.join(REPO_ROOT, "entrypoint.sh")

# USN-8847-1 (29.09.2026, 11 CVE, в т.ч. CVE-2026-84782 High). Константа
# дублируется из ci.yml осознанно: тест должен упасть, если минимум в
# workflow подняли/уронили молча — сверка двух мест.
LIBSSL_MIN = "3.0.13-0ubuntu3.16"


class DockerfileSecurityUpgrade(unittest.TestCase):
    """A.1: upgrade в том же слое, что и update; без пина версии."""

    @classmethod
    def setUpClass(cls):
        with open(DOCKERFILE, encoding="utf-8") as fh:
            cls.text = fh.read()

    def test_upgrade_in_same_layer_as_update(self):
        m = re.search(r"RUN apt-get update([^\n]*&&\s*\\?\s*\n?[^\n]*)*",
                      self.text)
        self.assertIsNotNone(m, "нет RUN apt-get update в Dockerfile")
        layer_start = m.start()
        install_m = re.search(r"apt-get install -y", self.text)
        self.assertIsNotNone(install_m)
        layer = self.text[layer_start:install_m.start()]
        self.assertIn("apt-get upgrade -y --no-install-recommends", layer,
                      "apt-get upgrade -y --no-install-recommends отсутствует "
                      "в слое между update и install (SEC-2 A.1)")

    def test_no_pinned_package_version(self):
        # Запрет наряда: не закреплять конкретную версию пакета в install.
        self.assertNotIn("libssl3t64=", self.text,
                         "версия libssl3t64 закреплена в apt-get — запрет "
                         "наряда (обновления должны приходить сами)")


class CiLibsslGate(unittest.TestCase):
    """A.1: CI падает при libssl3t64 ниже минимума."""

    @classmethod
    def setUpClass(cls):
        with open(CI, encoding="utf-8") as fh:
            cls.text = fh.read()

    def _gate(self):
        m = re.search(r"- name: Verify libssl3t64 >= minimum \(SEC-2\)"
                      r"(.*?)(?=\n      - name: |\n  # ── Job 5)",
                      self.text, re.S)
        self.assertIsNotNone(m, "шаг Verify libssl3t64 (SEC-2) не найден в "
                                "ci.yml job docker-build")
        return m.group(1)

    def test_gate_exists_in_docker_build_job(self):
        self.assertIn("dpkg --compare-versions", self._gate())

    def test_minimum_constant_usn_8847(self):
        self.assertIn(LIBSSL_MIN, self._gate(),
                      f"минимум {LIBSSL_MIN} (USN-8847-1) не найден в гейте")

    def test_gate_is_blocking_comparison(self):
        gate = self._gate()
        self.assertRegex(gate, r'dpkg --compare-versions "\$\{GOT\}" ge '
                               r'"\$\{LIBSSL_MIN\}"',
                         "гейт должен сравнивать GOT ge LIBSSL_MIN")
        self.assertIn("exit 1", gate, "гейт не блокирует (нет exit 1)")

    def test_gate_conditioned_on_docker_available(self):
        gate_block = self._gate()
        self.assertIn("steps.detect.outputs.available == 'yes'",
                      gate_block.split("run:")[0],
                      "шаг гейта должен быть условен как сборка "
                      "(available == 'yes')")


class EntrypointSecurityLine(unittest.TestCase):
    """A.2: строка версий в логе старта."""

    @classmethod
    def setUpClass(cls):
        with open(ENTRYPOINT, encoding="utf-8") as fh:
            cls.text = fh.read()

    def test_security_line_present(self):
        m = re.search(r'^echo "security: libssl3t64=.*openssl=.*"$',
                      self.text, re.M)
        self.assertIsNotNone(m, "строка security: libssl3t64/openssl "
                                "отсутствует в entrypoint.sh (SEC-2 A.2)")

    def test_dpkg_version_not_openssl_banner(self):
        line = re.search(r'^echo "security:.*$', self.text, re.M).group(0)
        self.assertEqual(line.count("dpkg-query -W -f='${Version}'"), 2,
                         "обе версии должны читаться dpkg-версией пакета "
                         "(бэкпорты не меняют строку 'openssl version')")

    def test_unknown_fallback_no_boot_failure(self):
        line = re.search(r'^echo "security:.*$', self.text, re.M).group(0)
        self.assertEqual(line.count("|| echo unknown"), 2,
                         "fallback unknown обязателен — строка не роняет бут")


if __name__ == "__main__":
    unittest.main()
