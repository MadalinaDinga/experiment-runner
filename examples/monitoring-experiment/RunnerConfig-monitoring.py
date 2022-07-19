import enum
import os
import paramiko
import time
from ConfigValidator.Config.Models.FactorModel import FactorModel
from ConfigValidator.Config.Models.OperationType import OperationType
from ConfigValidator.Config.Models.RunTableModel import RunTableModel
from ConfigValidator.Config.Models.RunnerContext import RunnerContext
from EventManager.EventSubscriptionController import EventSubscriptionController
from EventManager.Models.RunnerEvents import RunnerEvents
from ProgressManager.Output.OutputProcedure import OutputProcedure as output
from os.path import dirname, realpath
from pathlib import Path
from typing import Dict, List, Any, Optional


class Workload(enum.Enum):
    W_LOW = 25
    W_MEDIUM = 50
    W_HIGH = 100

def extract_level(level):
    # We remove the prefix and make it lowecase F_LOW -> low
    return level.lower()[2:]

def get_credentials(host_name):
    # declare credentials
    host = os.getenv(f"{host_name}_HOST")
    username = os.getenv(f"{host_name}_USERNAME")
    password = os.getenv(f"{host_name}_PASSWORD")

    if not password or not username or not host:
        raise Exception('No environment variables set for credentials')

    return host, username, password


class RunnerConfig:
    ROOT_DIR = Path(dirname(realpath(__file__)))

    # ================================ USER SPECIFIC CONFIG ================================
    """The name of the experiment."""
    name:                       str             = "new_runner_experiment"

    """The path in which Experiment Runner will create a folder with the name `self.name`, in order to store the
    results from this experiment. (Path does not need to exist - it will be created if necessary.)
    Output path defaults to the config file's path, inside the folder 'experiments'"""
    results_output_path:        Path             = ROOT_DIR / 'experiments'

    """Experiment operation type. Unless you manually want to initiate each run, use `OperationType.AUTO`."""
    operation_type:             OperationType   = OperationType.AUTO

    """The time Experiment Runner will wait after a run completes.
    This can be essential to accommodate for cooldown periods on some systems."""
    time_between_runs_in_ms:    int             = 3*60*1000


    # Dynamic configurations can be one-time satisfied here before the program takes the config as-is
    # e.g. Setting some variable based on some criteria
    def __init__(self):
        """Executes immediately after program start, on config load"""

        EventSubscriptionController.subscribe_to_multiple_events([
            (RunnerEvents.BEFORE_EXPERIMENT, self.before_experiment),
            (RunnerEvents.BEFORE_RUN       , self.before_run       ),
            (RunnerEvents.START_RUN        , self.start_run        ),
            (RunnerEvents.START_MEASUREMENT, self.start_measurement),
            (RunnerEvents.INTERACT         , self.interact         ),
            (RunnerEvents.STOP_MEASUREMENT , self.stop_measurement ),
            (RunnerEvents.STOP_RUN         , self.stop_run         ),
            (RunnerEvents.POPULATE_RUN_DATA, self.populate_run_data),
            (RunnerEvents.AFTER_EXPERIMENT , self.after_experiment )
        ])
        self.run_table = None  # Initialized later

        output.console_log("Custom config loaded")


    def create_run_table(self) -> List[Dict]:
        """Create and return the run_table here. A run_table is a List (rows) of tuples (columns), 
        representing each run performed"""
        self.run_table = RunTableModel(
            factors=[
                FactorModel("trial_number", ['t1', 't2', 't3', 't4', 't5', 't6', 't7', 't8', 't9', 't10']),
                FactorModel("tool", ['baseline', 'netdata', 'zipkin', 'prometheus', 'elastic', 'jaeger']),
                FactorModel("frequency", ['F_HIGH', 'F_MEDIUM', 'F_LOW']),
                FactorModel("workload", ['W_HIGH', 'W_MEDIUM', 'W_LOW']),
            ],
            exclude_variations=[{"baseline", "F_HIGH", "W_HIGH"},
                                {"baseline", "F_HIGH", "W_MEDIUM"},
                                {"baseline", "F_HIGH", "W_LOW"},
                                {"baseline", "F_MEDIUM", "W_HIGH"},
                                {"baseline", "F_MEDIUM", "W_MEDIUM"},
                                {"baseline", "F_MEDIUM", "W_LOW"}],
            data_columns=[]
        )
        return self.run_table.generate_experiment_run_table()


    def before_experiment(self) -> None:
        """Perform any activity required before starting the experiment here
        Invoked only once during the lifetime of the program."""

        output.console_log("Config.before_experiment() called!")


    def before_run(self) -> None:
        """Perform any activity required before starting a run.
        No context is available here as the run is not yet active (BEFORE RUN)"""

        output.console_log("Config.before_run() called!")


    def start_run(self, context: RunnerContext) -> None:
        """Perform any activity required for starting the run here.
        For example, starting the target system to measure.
        Activities after starting the run should also be performed here."""

        output.console_log("Config.start_run() called!")

        host, username, password = get_credentials('GL2')

        # connect to server
        con = paramiko.SSHClient()
        con.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        con.connect(host, username=username, password=password)

        output.console_log("Connection successful")

        tool = context.run_variation['tool']
        frequency = extract_level(context.run_variation['frequency'])
        output.console_log(f"Running {tool} with {frequency}")
        # run as sudo, since elastic requires it
        stdin, stdout, stderr = con.exec_command(f"tmux new -s train -d 'cd ~/train-ticket-fork/train-ticket; echo {password} | sudo -S python cli.py run-stack -t {tool} -f {frequency}'")

        output.console_log(f"Output: {stdout.read()}")

        err = stderr.read()
        if err != b'':
            output.console_log(err)
            self.interupt_run(context, "Encountered an error while starting system")

        output.console_log("Waiting for benchmark system to start up")

        # wait for system to start up
        if (context.run_variation['tool'] == 'elastic'):
            output.console_log("Sleep 10 minutes...")
            time.sleep(10*60)
        else:
            output.console_log("Sleep 5 minutes...")
            time.sleep(5*60)

        _, number_of_containers_buf, _ = con.exec_command("docker ps | wc -l")
        number_of_containers = int(number_of_containers_buf.read().strip())
        output.console_log(f"Found {number_of_containers} running after sleeping")

        if number_of_containers < 68:
            output.console_log(f"Not enough containers running: {number_of_containers}/68")
            # cleanup
            self.interupt_run(context, "Not all expected containers are running")

        output.console_log("Benchmark system initialized")

    def interupt_run(self, context, msg):
        self.stop_measurement(context)
        self.stop_run(context)
        output.console_log_FAIL(msg)
        raise Exception(msg)

    def start_measurement(self, context: RunnerContext) -> None:
        """Perform any activity required for starting measurements."""
        output.console_log("Config.start_measurement() called!")

        host, username, password = get_credentials('GL3')

        # connect to server
        con = paramiko.SSHClient()
        con.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        con.connect(host, username=username, password=password)

        output.console_log("Connection successful")
        output.console_log('Start Wattsup meter')

        file_name_suffix = context.run_variation['trial_number'] + "-" + context.run_variation['tool'] + "-" + context.run_variation['frequency'] + "-" + context.run_variation['workload']

        # start profiler (on GL3)
        stdin, stdout, stderr = con.exec_command(f"echo {password} | sudo -S ~/wattsup/start_wattsup_new.sh {file_name_suffix} {context.run_variation['trial_number']} train-ticket")

        err = stderr.read()
        if err != b'':
            output.console_log(err)

        output.console_log('Wattsup successfully started')


    def interact(self, context: RunnerContext) -> None:
        """Perform any interaction with the running target system here, or block here until the target finishes."""

        output.console_log("Config.interact() called!")
        workload_value = Workload[context.run_variation['workload']].value
        output.console_log(f"Load testing with K6 - {context.run_variation['workload']} workload: {workload_value}")

        os.system(f"for i in $(ls ~/train-ticket/k6-test); "
                  f"do k6 run - <~/train-ticket/k6-test/$i/script.js --vus {workload_value} --duration 20s ; done")

        output.console_log('Finished load testing')


    def stop_measurement(self, context: RunnerContext) -> None:
        """Perform any activity here required for stopping measurements."""

        output.console_log("Config.stop_measurement called!")

        host, username, password = get_credentials('GL3')

        # connect to server
        con = paramiko.SSHClient()
        con.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        con.connect(host, username=username, password=password)

        output.console_log("Connection successful")

        output.console_log('Stopping Wattsup meter')

        # stop profiler (on GL3)
        stdin, stdout, stderr = con.exec_command(f"echo {password} | sudo -S ~/wattsup/stop_wattsup.sh")

        err = stderr.read()
        if err != b'':
            output.console_log(err)

        output.console_log('Stopped Wattsup meter')


    def stop_run(self, context: RunnerContext) -> None:
        """Perform any activity here required for stopping the run.
        Activities after stopping the run should also be performed here."""

        output.console_log("Config.stop_run() called!")

        host, username, password = get_credentials('GL2')

        # connect to server
        con = paramiko.SSHClient()
        con.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        con.connect(host, username=username, password=password)

        output.console_log("Connection successful")

        # run as sudo, since elastic cleanup requires it
        stdin, stdout, stderr = con.exec_command(f"cd ~/train-ticket-fork/train-ticket; echo {password} | sudo -S python cli.py cleanup -t {context.run_variation['tool']}")

        err = stderr.read()
        if err != b'':
            output.console_log(err)

        output.console_log('Stopped benchmark system')

        output.console_log('Prune volumes')

        stdin, stdout, stderr = con.exec_command(f"echo y | docker volume prune")

        err = stderr.read()
        if err != b'':
            output.console_log(err)

        output.console_log('Restart docker system')

        stdin, stdout, stderr = con.exec_command(f"echo {password} | sudo -S systemctl restart docker.service")

        err = stderr.read()
        if err != b'':
            output.console_log(err)

        output.console_log('Kill tmux session')

        stdin, stdout, stderr = con.exec_command(f"tmux kill-session -t train")

        err = stderr.read()
        if err != b'':
            output.console_log(err)


    def populate_run_data(self, context: RunnerContext) -> Optional[Dict[str, Any]]:
        """Parse and process any measurement data here.
        You can also store the raw measurement data under `context.run_dir`
        Returns a dictionary with keys `self.run_table.data_columns` and their values populated"""

        output.console_log("Config.populate_run_data() called!")
        return None


    def after_experiment(self) -> None:
        """Perform any activity required after stopping the experiment here
        Invoked only once during the lifetime of the program."""

        output.console_log("Config.after_experiment() called!")


    # ================================ DO NOT ALTER BELOW THIS LINE ================================
    experiment_path:            Path             = None
