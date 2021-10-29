import json
from enum import IntEnum
from typing import Dict
from typing import List
from typing import Optional

try:
    import qiskit
except ImportError:
    raise ImportError(
        '`qiskit` was not found, try to `pip install "quantum-viz[qiskit]"`'
    )

from qiskit.circuit import QuantumCircuit, Qubit, Clbit
from qiskit.circuit.instruction import Instruction
from qiskit.circuit.controlledgate import ControlledGate
from qiskit.circuit.measure import Measure
from qiskit.circuit.barrier import Barrier
from qiskit.circuit.reset import Reset
from qiskit.circuit.library import IGate, SXGate, SXdgGate

X_GATE_NAME = "X"
MEASURE_NAME = Measure().name


class RegisterType(IntEnum):
    QUBIT = 0
    CLASSICAL = 1


class ConditionalRender(IntEnum):
    ALWAYS = 0
    ON_ZERO = 1
    ON_ONE = 2
    AS_GROUP = 3


def qiskit2json(circ: qiskit.QuantumCircuit, indent=2, **kwargs) -> str:
    return json.dumps(qiskit2dict(circ, **kwargs), indent=indent)


def qiskit2dict(circ: qiskit.QuantumCircuit, **kwargs) -> dict:
    return QiskitCircuitParser(circ, **kwargs).qviz_dict


class QiskitCircuitParser:
    QUBITS_KEY = "qubits"
    OPERATIONS_KEY = "operations"
    UPPERCASE = ["x", "y", "z", "h", "s", "t", "u", "p", "r", "swap"]
    CAPITALIZE = [
        "rx",
        "ry",
        "rz",
        "rxx",
        "ryy",
        "rzx",
        "rzz",
        "u1",
        "u2",
        "u3",
        "tdg",
        "sdg",
        "iswap",
        "dcx",
    ]
    SPECIAL_MAPPER = {IGate: "I", SXGate: "√X", SXdgGate: "√Xdg"}
    SPECIAL_GATES = tuple(SPECIAL_MAPPER.keys())

    def __init__(self, circuit: QuantumCircuit, precision=2) -> None:
        self.qc: QuantumCircuit = circuit
        self.precision = precision
        self.qviz_dict: Dict[str, List] = {
            self.QUBITS_KEY: [],
            self.OPERATIONS_KEY: [],
        }
        self.qubit2id: Dict[Qubit, int] = dict()
        self.init_qubits()
        self._clbit2id: Dict[Clbit, (Qubit, int)] = dict()
        self.update_qviz_dict()

    def init_qubits(self) -> None:
        qubits = self.qc.qubits + self.qc.ancillas
        num_qubits = self.qc.num_qubits + self.qc.num_ancillas
        qubits_range = range(num_qubits)
        self.qubit2id = dict(zip(qubits, qubits_range))
        self.qviz_dict[self.QUBITS_KEY] = [{"id": i} for i in qubits_range]

    @property
    def qubits(self) -> List[Dict[str, int]]:
        return self.qviz_dict[self.QUBITS_KEY]

    @qubits.setter
    def qubits(self, value: List[Dict[str, int]]) -> None:
        self.qviz_dict[self.QUBITS_KEY] = value

    def _get_qubit_def(self, qubit: Qubit) -> Dict[str, int]:
        return {"qId": self.qubit2id[qubit]}

    def _get_qubit_list_def(self, qubits: List[Qubit]) -> List[Dict[str, int]]:
        return [self._get_qubit_def(qubit) for qubit in qubits]

    def _get_clbit_def(
        self, clbit: Clbit, qubit: Optional[Qubit] = None
    ) -> Dict[str, int]:
        if clbit in self._clbit2id:
            qubit, c_id = self._clbit2id[clbit]
            q_id = self.qubit2id[qubit]
        else:
            if qubit is None:
                raise NotImplementedError(
                    "A classical bit has to defined first as a measurement result of a "
                    "qubit"
                )
            q_id = self.qubit2id[qubit]
            c_id = self.qubits[q_id].get("numChildren", 0)
            self.qubits[q_id]["numChildren"] = c_id + 1
            self._clbit2id[clbit] = (qubit, c_id)
        return {"type": RegisterType.CLASSICAL.value, "qId": q_id, "cId": c_id}

    def update_qviz_dict(self) -> None:
        qc = self.qc
        self.qviz_dict[self.OPERATIONS_KEY] += [
            {
                "gate": qc.name,
                "children": [
                    self.parse_operation(instruction, qargs, cargs)
                    for instruction, qargs, cargs in qc.data
                ],
                "targets": self._get_qubit_list_def(qc.qubits + qc.ancillas),
            }
        ]

    def parse_operation(
        self, instruction: Instruction, qargs: List[Qubit], cargs: List[Clbit]
    ) -> Optional[Dict]:

        if isinstance(instruction, Barrier) or instruction.condition is not None:
            raise NotImplementedError

        op_dict = {"gate": instruction.name}

        if instruction.params:
            f"({', '.join(map('{:.2f}'.format, instruction.params))})"
            mapper = map(f"{{:.{self.precision}f}}".format, instruction.params)
            op_dict["displayArgs"] = f"({', '.join(mapper)})"

        if isinstance(instruction, Reset):
            self.add_reset(op_dict, qubit=qargs[0])

        elif isinstance(instruction, Measure):
            if len(qargs) != 1 or len(cargs) != 1:
                raise ValueError
            qubit = qargs[0]
            clbit = cargs[0]
            op_dict["isMeasurement"] = True
            op_dict["controls"] = [self._get_qubit_def(qubit)]
            op_dict["targets"] = [self._get_clbit_def(clbit, qubit)]

        elif isinstance(instruction, ControlledGate):
            ctrl_state = instruction.ctrl_state
            if not all([int(c) for c in str(ctrl_state)]):
                raise NotImplementedError(
                    f"The controlled gate {instruction} is controlled by a state that "
                    f"is not all 1's: {ctrl_state}"
                )
            num_ctrl_qubits = instruction.num_ctrl_qubits
            ctrl_qubits = qargs[:num_ctrl_qubits]
            target_qubits = qargs[num_ctrl_qubits:]
            op_dict["isControlled"] = True
            op_dict["gate"] = instruction.base_gate.name
            op_dict["controls"] = self._get_qubit_list_def(ctrl_qubits)
            op_dict["targets"] = self._get_qubit_list_def(target_qubits)

        else:
            op_dict["targets"] = self._get_qubit_list_def(qargs)

        name = op_dict["gate"]
        if name in self.UPPERCASE:
            op_dict["gate"] = name.upper()
        elif name in self.CAPITALIZE:
            op_dict["gate"] = name.capitalize()
        elif isinstance(instruction, self.SPECIAL_GATES):
            op_dict["gate"] = self.SPECIAL_MAPPER[type(instruction)]

        if instruction.definition is not None:
            sub_circuit: QuantumCircuit = instruction.definition
            op_dict["children"] = []
            for sub_instruction, sub_qargs, sub_cargs in sub_circuit.data:
                sub_qargs = [qargs[qubit.index] for qubit in sub_qargs]
                sub_cargs = [cargs[clbit.index] for clbit in sub_cargs]
                op_dict["children"] += [
                    self.parse_operation(sub_instruction, sub_qargs, sub_cargs)
                ]

        return op_dict

    def add_reset(self, op_dict: Dict, qubit: Qubit) -> None:
        """Reset logic - measure and apply X gate if the measurement yields 1"""
        qubit_def = self._get_qubit_def(qubit)
        op_dict["targets"] = [qubit_def]
        clbit_def = self._get_clbit_def(Clbit(), qubit)  # create a new classical bit

        op_dict["children"] = [
            {
                "gate": MEASURE_NAME,
                "isMeasurement": True,
                "controls": [qubit_def],
                "targets": [clbit_def],
            },
            {
                "gate": "Conditional",
                "isConditional": True,
                "controls": [clbit_def],
                "targets": [],
                "children": [
                    {
                        "gate": X_GATE_NAME,
                        "targets": [qubit_def],
                        "conditionalRender": ConditionalRender.ON_ONE,
                    }
                ],
            },
        ]
