language: PYTHON
name: "bayOpt"

variable {
    name: "cpu_quota"
    type: FLOAT
    size: 1
    min: 1
    max: 100
}

variable {
    name: "cpu_count"
    type: FLOAT
    size: 1
    min: 2
    max: 8
}

variable {
    name: "machine_count"
    type: FLOAT
    size: 1
    min: 2
    max: 7
}
