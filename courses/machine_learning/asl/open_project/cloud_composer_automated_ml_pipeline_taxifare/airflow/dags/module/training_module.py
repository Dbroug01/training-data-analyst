# Copyright 2018 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""DAG definition for anadarko composer toy model training."""

import airflow
from airflow import DAG

# Reference for all available airflow operators: 
# https://github.com/apache/incubator-airflow/tree/master/airflow/contrib/operators
# from airflow.contrib.operators.bigquery_operator import BigQueryOperator
# from airflow.contrib.operators.bigquery_check_operator import BigQueryCheckOperator
# from airflow.contrib.operators.bigquery_to_gcs import BigQueryToCloudStorageOperator
# from airflow.operators.bash_operator import BashOperator
# from airflow.operators.python_operator import BranchPythonOperator
# from airflow.operators.dummy_operator import DummyOperator
from airflow.hooks.base_hook import BaseHook

# from airflow.contrib.operators.mlengine_operator import MLEngineTrainingOperator, MLEngineModelOperator, MLEngineVersionOperator
from airflow.models import TaskInstance

import datetime
# import logging

from module import preprocess
from module import training
from module import deploy

# from module.preprocess import preprocess_tasks
# from module.training import training_tasks
# from module.deploy import deploy_tasks

def _get_project_id():
  """Get project ID from default GCP connection."""

  extras = BaseHook.get_connection("google_cloud_default").extra_dejson
  key = "extra__google_cloud_platform__project"
  if key in extras:
    project_id = extras[key]
  else:
    raise ("Must configure project_id in google_cloud_default "
           "connection from Airflow Console")
  return project_id

# Constants
# Get project ID and GCS bucket
PROJECT_ID = _get_project_id()
BUCKET = "gs://" + PROJECT_ID + "-bucket"

# Specify your source BigQuery dataset and table names
SOURCE_DATASET_TABLE_NAMES = "yellow.trips,green.trips_2014,green.trips_2015".split(",")

# Where to write out data in GCS
DATA_DIR = BUCKET + "/taxifare/data/"

# Base model parameters
MODEL_NAME = "taxifare_"
MODEL_VERSION = "v1"
MODEL_LOCATION = BUCKET + "/taxifare/saved_model/"

default_args = {
  "owner": "airflow",
  "depends_on_past": False,
  "start_date": airflow.utils.dates.days_ago(2),
  "email": ["airflow@example.com"],
  "email_on_failure": True,
  "email_on_retry": False,
  "retries": 5,
  "retry_delay": datetime.timedelta(minutes = 5)
}

# Default schedule interval using cronjob syntax - can be customized here
# or in the Airflow console.

# Specify a schedule interval in CRON syntax to run once a day at 2100 hours (9pm)
# Reference: https://airflow.apache.org/scheduler.html
schedule_interval = "00 21 * * *"

# TODO: Title your DAG to be recommendations_training_v1
dag = DAG(
  "training_module", 
  default_args = default_args,
  schedule_interval = None
)

dag.doc_md = __doc__


#
#
# Task Definition
#
#

for model in SOURCE_DATASET_TABLE_NAMES:
  (bq_train_data_op,
   bq_eval_data_op,
   bq_check_train_data_op,
   bq_check_eval_data_op,
   bash_remove_old_data_op,
   bq_export_gcs_train_csv_op,
   bq_export_gcs_eval_csv_op) = preprocess.preprocess_tasks(
       model, dag, PROJECT_ID, BUCKET, DATA_DIR)


  (ml_engine_training_op,
   bash_remove_old_saved_model_op,
   bash_copy_new_saved_model_op) = training.training_tasks(
       model, dag, PROJECT_ID, BUCKET, DATA_DIR, MODEL_NAME, MODEL_VERSION, MODEL_LOCATION)

  (bash_ml_engine_models_list_op,
   check_if_model_already_exists_op,
   ml_engine_create_model_op,
   create_model_dummy_op,
   dont_create_model_dummy_branch_op,
   dont_create_model_dummy_op,
   bash_ml_engine_versions_list_op,
   check_if_model_version_already_exists_op,
   ml_engine_create_version_op,
   ml_engine_create_other_version_op,
   ml_engine_set_default_version_op,
   ml_engine_set_default_other_version_op) = deploy.deploy_tasks(
       model, dag, PROJECT_ID, MODEL_NAME, MODEL_VERSION, MODEL_LOCATION)

  # Build dependency graph, set_upstream dependencies for all tasks
  bq_check_train_data_op.set_upstream(bq_train_data_op)
  bq_check_eval_data_op.set_upstream(bq_eval_data_op)

  bash_remove_old_data_op.set_upstream([bq_check_train_data_op, bq_check_eval_data_op])

  bq_export_gcs_train_csv_op.set_upstream([bash_remove_old_data_op])
  bq_export_gcs_eval_csv_op.set_upstream([bash_remove_old_data_op])

  ml_engine_training_op.set_upstream([bq_export_gcs_train_csv_op, bq_export_gcs_eval_csv_op])

  bash_remove_old_saved_model_op.set_upstream(ml_engine_training_op)
  bash_copy_new_saved_model_op.set_upstream(bash_remove_old_saved_model_op)

  bash_ml_engine_models_list_op.set_upstream(ml_engine_training_op)
  check_if_model_already_exists_op.set_upstream(bash_ml_engine_models_list_op)

  ml_engine_create_model_op.set_upstream(check_if_model_already_exists_op)
  create_model_dummy_op.set_upstream(ml_engine_create_model_op)
  dont_create_model_dummy_branch_op.set_upstream(check_if_model_already_exists_op)
  dont_create_model_dummy_op.set_upstream(dont_create_model_dummy_branch_op)

  bash_ml_engine_versions_list_op.set_upstream([dont_create_model_dummy_op, create_model_dummy_op])
  check_if_model_version_already_exists_op.set_upstream(bash_ml_engine_versions_list_op)

  ml_engine_create_version_op.set_upstream([bash_copy_new_saved_model_op, check_if_model_version_already_exists_op])
  ml_engine_create_other_version_op.set_upstream([bash_copy_new_saved_model_op, check_if_model_version_already_exists_op])

  ml_engine_set_default_version_op.set_upstream(ml_engine_create_version_op)
  ml_engine_set_default_other_version_op.set_upstream(ml_engine_create_other_version_op)
