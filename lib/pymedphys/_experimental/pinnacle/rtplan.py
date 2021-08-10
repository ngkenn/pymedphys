# Copyright (C) 2019 South Western Sydney Local Health District,
# University of New South Wales

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This work is derived from:
# https://github.com/AndrewWAlexander/Pinnacle-tar-DICOM
# which is released under the following license:

# Copyright (c) [2017] [Colleen Henschel, Andrew Alexander]

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


import os
import re
import time
import json
from pymedphys._imports import pydicom
from typing import Dict, List
from .constants import (
    GImplementationClassUID,
    GTransferSyntaxUID,
    Manufacturer,
    RTPLANModality,
    RTPlanSOPClassUID,
    RTStructSOPClassUID,
)


def convert_plan(plan, export_path):

    # Check that the plan has a primary image, as we can't create a meaningful RTPLAN without it:
    if not plan.primary_image:
        plan.logger.error("No primary image found for plan. Unable to generate RTPLAN.")
        return

    # TODO Fix the RTPLAN export functionality and remove this warning
    plan.logger.warning(
        "RTPLAN export functionality is currently not validated and not stable. Use with caution."
    )

    patient_info = plan.pinnacle.patient_info
    plan_info = plan.plan_info
    trial_info = plan.trial_info
    image_info = plan.primary_image.image_info[0]
    machine_info = plan.machine_info

    patient_position = plan.patient_position

    # Get the UID for the Plan
    planInstanceUID = plan.plan_inst_uid

    # Populate required values for file meta information
    file_meta = pydicom.dataset.Dataset()
    file_meta.MediaStorageSOPClassUID = RTPlanSOPClassUID
    file_meta.TransferSyntaxUID = GTransferSyntaxUID
    file_meta.MediaStorageSOPInstanceUID = planInstanceUID
    file_meta.ImplementationClassUID = GImplementationClassUID

    # Create the pydicom.dataset.FileDataset instance (initially no data elements, but
    # file_meta supplied)
    RPfilename = f"RP.{file_meta.MediaStorageSOPInstanceUID}.dcm"
    ds = pydicom.dataset.FileDataset(
        RPfilename, {}, file_meta=file_meta, preamble=b"\x00" * 128
    )

    ds.SpecificCharacterSet = "ISO_IR 100"
    ds.InstanceCreationDate = time.strftime("%Y%m%d")
    ds.InstanceCreationTime = time.strftime("%H%M%S")

    ds.SOPClassUID = RTPlanSOPClassUID  # RT Plan Storage
    ds.SOPInstanceUID = planInstanceUID

    datetimesplit = plan_info["ObjectVersion"]["WriteTimeStamp"].split()

    # Read more accurate date from trial file if it is available
    trial_info = plan.trial_info
    if trial_info:
        datetimesplit = trial_info["ObjectVersion"]["WriteTimeStamp"].split()

    ds.StudyDate = datetimesplit[0].replace("-", "")
    ds.StudyTime = datetimesplit[1].replace(":", "")
    ds.AccessionNumber = ""
    ds.Modality = RTPLANModality
    ds.Manufacturer = Manufacturer
    ds.OperatorsName = ""
    ds.ManufacturersModelName = plan_info["ToolType"]
    ds.SoftwareVersions = [plan_info["PinnacleVersionDescription"]]
    ds.PhysiciansOfRecord = patient_info["RadiationOncologist"]
    ds.PatientName = patient_info["FullName"]
    ds.PatientBirthDate = patient_info["DOB"]
    ds.PatientID = patient_info["MedicalRecordNumber"]
    ds.PatientSex = patient_info["Gender"][0]

    ds.StudyInstanceUID = image_info["StudyInstanceUID"]
    ds.SeriesInstanceUID = planInstanceUID
    ds.StudyID = plan.primary_image.image["StudyID"]

    ds.FrameOfReferenceUID = image_info["FrameUID"]
    ds.PositionReferenceIndicator = ""

    ds.RTPlanLabel = f"{plan.plan_info['PlanName']}.0"
    ds.RTPlanName = plan.plan_info["PlanName"]
    ds.RTPlanDescription = plan.pinnacle.patient_info["Comment"]
    ds.RTPlanDate = ds.StudyDate
    ds.RTPlanTime = ds.StudyTime

    # ds.PlanIntent = "" #Not sure where to get this informationd, will likely
    # be 'CURATIVE' or 'PALLIATIVE'
    ds.RTPlanGeometry = "PATIENT"
    # Figure out what goes in DoseReferenceSequence... Should be like a target volume and
    # reference point I think...
    # ds.DoseReferenceSequence = pydicom.sequence.Sequence()
    # figure out where to get this information
    # ds.ToleranceTableSequence = pydicom.sequence.Sequence()
    ds.FractionGroupSequence = pydicom.sequence.Sequence()
    ds.BeamSequence = pydicom.sequence.Sequence()
    ds.PatientSetupSequence = pydicom.sequence.Sequence()  # need one per beam
    ds.ReferencedStructureSetSequence = pydicom.sequence.Sequence()
    ReferencedStructureSet1 = pydicom.dataset.Dataset()
    ds.ReferencedStructureSetSequence.append(ReferencedStructureSet1)
    ds.ReferencedStructureSetSequence[0].ReferencedSOPClassUID = RTStructSOPClassUID
    ds.ReferencedStructureSetSequence[0].ReferencedSOPInstanceUID = plan.struct_inst_uid
    ds.ApprovalStatus = "UNAPPROVED"  # find out where to get this information

    ds.FractionGroupSequence.append(pydicom.dataset.Dataset())
    ds.FractionGroupSequence[0].ReferencedBeamSequence = pydicom.sequence.Sequence()

    metersetweight = ["0"]

    num_fractions = 0
    beam_count = 0
    beam_list = trial_info["BeamList"] if trial_info["BeamList"] else []
    if len(beam_list) == 0:
        plan.logger.warning("No Beams found in Trial. Unable to generate RTPLAN.")
        return

    # with open(f"/home/neil/{ds.PatientID}_plan/trial.json", "w") as tfile:
    #     json.dump(trial_info, tfile)
    # with open(f"/home/neil/{ds.PatientID}_plan/plan_info.json", "w") as tfile:
    #     json.dump(plan_info, tfile)
    # with open(f"/home/neil/{ds.PatientID}_plan/image_info.json", "w") as tfile:
    #     json.dump(image_info, tfile)
    # with open(f"/home/neil/{ds.PatientID}_plan/machine_info.json", "w") as tfile:
    #     json.dump(machine_info, tfile)
    for beam_count, beam in enumerate(beam_list):
        # print(beam_list)
        # with open(f"/home/neil/{ds.PatientID}_beam.json", "w") as tfile:
        #     json.dump(beam, tfile)

        ds.PatientSetupSequence.append(pydicom.dataset.Dataset())

        plan.logger.info("Exporting Plan for beam: %s", beam["Name"])

        ds.PatientSetupSequence.append(pydicom.dataset.Dataset())
        ds.PatientSetupSequence[beam_count].PatientPosition = patient_position
        ds.PatientSetupSequence[beam_count].PatientSetupNumber = beam_count

        ds.FractionGroupSequence[0].ReferencedBeamSequence.append(
            pydicom.dataset.Dataset()
        )
        ds.FractionGroupSequence[0].ReferencedBeamSequence[
            beam_count
        ].ReferencedBeamNumber = beam_count
        ds.BeamSequence.append(pydicom.dataset.Dataset())
        # figure out what to put here
        beam_sequence = ds.BeamSequence[beam_count]

        beam_sequence.Manufacturer = Manufacturer
        beam_sequence.BeamNumber = beam_count
        beam_sequence.TreatmentDeliveryType = "TREATMENT"
        beam_sequence.ReferencedPatientSetupNumber = beam_count
        beam_sequence.SourceAxisDistance = "1000"
        beam_sequence.FinalCumulativeMetersetWeight = "1"
        beam_sequence.PrimaryDosimeterUnit = "MU"
        beam_sequence.PrimaryFluenceModeSequence = pydicom.sequence.Sequence()
        beam_sequence.PrimaryFluenceModeSequence.append(pydicom.dataset.Dataset())
        beam_sequence.PrimaryFluenceModeSequence[0].FluenceMode = "STANDARD"

        beam_sequence.BeamName = beam["FieldID"]
        beam_sequence.BeamDescription = beam["Name"]

        beam_ssd = beam["SSD"]

        if "Photons" in beam["Modality"]:
            beam_sequence.RadiationType = "PHOTON"
        elif "Electrons" in beam["Modality"]:
            beam_sequence.RadiationType = "ELECTRON"
        else:
            beam_sequence.RadiationType = ""

        if "STATIC" in beam["SetBeamType"].upper():
            beam_sequence.BeamType = beam["SetBeamType"].upper()
        else:
            beam_sequence.BeamType = "DYNAMIC"

        beam_sequence.TreatmentMachineName = beam["MachineNameAndVersion"].partition(
            ":"
        )[0]

        doserefpt = None
        for point in plan.points:
            if point["Name"] == beam["PrescriptionPointName"]:
                doserefpt = plan.convert_point(point)
                plan.logger.debug("Dose reference point found: %s", point["Name"])

        if not doserefpt:
            plan.logger.debug("No dose reference point, setting to isocenter")
            doserefpt = plan.iso_center

        plan.logger.debug("Dose reference point: %s", doserefpt)

        ds.FractionGroupSequence[0].ReferencedBeamSequence[
            beam_count
        ].BeamDoseSpecificationPoint = doserefpt

        beam_sequence.ControlPointSequence = pydicom.sequence.Sequence()

        cp_manager = {}
        if "CPManagerObject" in beam["CPManager"]:
            cp_manager = beam["CPManager"]["CPManagerObject"]
        else:
            cp_manager = beam["CPManager"]

        numctrlpts = cp_manager["NumberOfControlPoints"]

        cumulativeMetersetWeight = 0.0
        plan.logger.debug("Number of control points: %s", numctrlpts)

        # CONTROL POINTS
        # Loop through the cp indices and map them to dicom
        for cp_index, cp in enumerate(cp_manager["ControlPointList"]):

            metersetweight.append(cp["Weight"])
            currentMetersetWeight = cp["Weight"]

            cp_ssd = (
                beam_ssd * 10
            )  # TODO review. This is wrong - the SSD changes each CP

            # TODO round to ints?
            x1 = -cp["RightJawPosition"] * 10
            x2 = cp["LeftJawPosition"] * 10
            y1 = -cp["TopJawPosition"] * 10
            y2 = cp["BottomJawPosition"] * 10

            points = cp["MLCLeafPositions"]["RawData"]["Points[]"].split(",")
            p_count = 0
            n_points = len(points)
            leafpositions1 = []
            leafpositions2 = []
            for p in points:
                leafpoint = float(p.strip())
                if p_count % 2 == 0:
                    leafpositions1.append(-leafpoint * 10)
                else:
                    leafpositions2.append(leafpoint * 10)
                p_count += 1

                if p_count == len(points):
                    leafpositions1 = list(reversed(leafpositions1))
                    leafpositions2 = list(reversed(leafpositions2))
                    leafpositions = leafpositions1 + leafpositions2

            gantryangle = cp["Gantry"]
            colangle = cp["Collimator"]
            psupportangle = cp["Couch"]

            (
                numwedges,
                wedgename,
                wedgeorientation,
                wedgeangle,
                wedgetype,
            ) = getWedgeInfo(cp, plan)

            # Get the prescription for this beam
            prescription = [
                p
                for p in trial_info["PrescriptionList"]
                if p["Name"] == beam["PrescriptionName"]
            ][0]

            # Get the machine name and version and energy name for this beam
            machinenameandversion = beam["MachineNameAndVersion"].split(": ")
            machinename = machinenameandversion[0]
            machineversion = machinenameandversion[1]
            machineenergyname = beam["MachineEnergyName"]

            beam_energy = re.findall(r"[-+]?\d*\.\d+|\d+", beam["MachineEnergyName"])[0]

            # Find the DosePerMuAtCalibration parameter from the machine data
            dose_per_mu_at_cal = -1
            if (
                machine_info["Name"] == machinename
                and machine_info["VersionTimestamp"] == machineversion
            ):

                for energy in machine_info["PhotonEnergyList"]:

                    if energy["Name"] == machineenergyname:
                        dose_per_mu_at_cal = energy["PhysicsData"]["OutputFactor"][
                            "DosePerMuAtCalibration"
                        ]
                        plan.logger.debug(
                            "Using DosePerMuAtCalibration of: %s", dose_per_mu_at_cal
                        )

            prescripdose = beam["MonitorUnitInfo"]["PrescriptionDose"]
            normdose = beam["MonitorUnitInfo"]["NormalizedDose"]

            if normdose == 0:
                ds.FractionGroupSequence[0].ReferencedBeamSequence[
                    beam_count
                ].BeamMeterset = 0
            else:
                ds.FractionGroupSequence[0].ReferencedBeamSequence[
                    beam_count
                ].BeamDose = (prescripdose / 100)
                ds.FractionGroupSequence[0].ReferencedBeamSequence[
                    beam_count
                ].BeamMeterset = prescripdose / (normdose * dose_per_mu_at_cal)
                beammeterset = prescripdose / (normdose * dose_per_mu_at_cal)

            gantryrotdir = "NONE"
            if (
                "GantryIsCCW" in cp_manager
            ):  # This may be a problem here!!!! Not sure how to Pinnacle does this, could
                # be 1 if CW, must be somewhere that states if gantry is rotating or not
                if cp_manager["GantryIsCCW"] == 1:
                    gantryrotdir = "CC"
            if "GantryIsCW" in cp_manager:
                if cp_manager["GantryIsCW"] == 1:
                    gantryrotdir = "CW"

            plan.logger.debug(
                "Beam MU: %s",
                ds.FractionGroupSequence[0]
                .ReferencedBeamSequence[beam_count]
                .BeamMeterset,
            )

            doserate = 0
            if (
                "DoseRate" in beam
            ):  # TODO What to do if DoseRate isn't available in Beam?
                doserate = beam["DoseRate"]

            beam_sequence = mapBeamDeviceLimitingSequence(
                beam_sequence, n_points, machine_info
            )

            # # TODO work out what to do with stepped beams
            # if (
            #     "STEP" in beam["SetBeamType"].upper()
            #     and "SHOOT" in beam["SetBeamType"].upper()
            # ):
            #     print("STEP BABAY")

            #     ctrlpt_range = numctrlpts * 2
            #     is_stepwise = True

            #     if cp_index % 2 == 1:
            #         currentmeterset = currentmeterset + float(
            #             metersetweight[metercount]
            #         )
            #         metercount += 1

            # else:
            #     print("NOT STEPWISE")
            #     ctrlpt_range = numctrlpts
            #     is_stepwise = False

            # for ctrlpt_index in range(0, ctrlpt_range):
            beam_sequence = mapBeamControlPointSequence(
                cp_index,
                beam_sequence,
                beam_energy,
                cp_ssd,
                doserate,
                leafpositions,
                plan.iso_center,
                gantryrotdir,
                gantryangle,
                colangle,
                psupportangle,
                numwedges,
                cumulativeMetersetWeight,
                currentMetersetWeight,
                x1,
                x2,
                y1,
                y2,
            )

            cumulativeMetersetWeight += currentMetersetWeight
        # Get the prescription for this beam
        prescription = [
            p
            for p in trial_info["PrescriptionList"]
            if p["Name"] == beam["PrescriptionName"]
        ][0]

        # Get the machine name and version and energy name for this beam
        machinenameandversion = beam["MachineNameAndVersion"].split(": ")
        machinename = machinenameandversion[0]
        machineversion = machinenameandversion[1]
        machineenergyname = beam["MachineEnergyName"]

        beam_energy = re.findall(r"[-+]?\d*\.\d+|\d+", beam["MachineEnergyName"])[0]

        # Find the DosePerMuAtCalibration parameter from the machine data
        dose_per_mu_at_cal = -1
        if (
            machine_info["Name"] == machinename
            and machine_info["VersionTimestamp"] == machineversion
        ):

            for energy in machine_info["PhotonEnergyList"]:

                if energy["Name"] == machineenergyname:
                    dose_per_mu_at_cal = energy["PhysicsData"]["OutputFactor"][
                        "DosePerMuAtCalibration"
                    ]
                    plan.logger.debug(
                        "Using DosePerMuAtCalibration of: %s", dose_per_mu_at_cal
                    )

        prescripdose = beam["MonitorUnitInfo"]["PrescriptionDose"]
        normdose = beam["MonitorUnitInfo"]["NormalizedDose"]

        if normdose == 0:
            ds.FractionGroupSequence[0].ReferencedBeamSequence[
                beam_count
            ].BeamMeterset = 0
        else:
            ds.FractionGroupSequence[0].ReferencedBeamSequence[beam_count].BeamDose = (
                prescripdose / 100
            )
            ds.FractionGroupSequence[0].ReferencedBeamSequence[
                beam_count
            ].BeamMeterset = prescripdose / (normdose * dose_per_mu_at_cal)

        gantryrotdir = "NONE"
        if (
            "GantryIsCCW" in cp_manager
        ):  # This may be a problem here!!!! Not sure how to Pinnacle does this, could
            # be 1 if CW, must be somewhere that states if gantry is rotating or not
            if cp_manager["GantryIsCCW"] == 1:
                gantryrotdir = "CC"
        if "GantryIsCW" in cp_manager:
            if cp_manager["GantryIsCW"] == 1:
                gantryrotdir = "CW"

        plan.logger.debug(
            "Beam MU: %s",
            ds.FractionGroupSequence[0].ReferencedBeamSequence[beam_count].BeamMeterset,
        )

        doserate = 0
        if "DoseRate" in beam:  # TODO What to do if DoseRate isn't available in Beam?
            doserate = beam["DoseRate"]

        prescription = [
            p
            for p in trial_info["PrescriptionList"]
            if p["Name"] == beam["PrescriptionName"]
        ][0]
        num_fractions = prescription["NumberOfFractions"]

    ds.FractionGroupSequence[0].FractionGroupNumber = 1
    ds.FractionGroupSequence[0].NumberOfFractionsPlanned = num_fractions
    ds.FractionGroupSequence[0].NumberOfBeams = beam_count
    ds.FractionGroupSequence[0].NumberOfBrachyApplicationSetups = "0"

    # Save the RTPlan Dicom File
    output_file = os.path.join(export_path, RPfilename)
    plan.logger.info("Creating Plan file: %s", output_file)
    ds.save_as(output_file)


def list_get(l, idx, default):
    try:
        return l[idx]
    except IndexError:
        return default


def mapBeam():
    beam_sequence.NumberOfControlPoints = numctrlpts * 2
    beam_sequence.SourceToSurfaceDistance = beam["SSD"] * 10

    pass


def mapBeamWedgeSequence():
    pass


def mapBeamDeviceLimitingSequence(beam_sequence, n_points, machine_info):
    """
    Appends the relevant BeamLimitingDevice Sequence objects to the supplied beam_sequence object
    """

    sourceToLeftRightDistance = machine_info["SourceToLeftRightJawDistance"]
    sourceToTopBottomDistance = machine_info["SourceToTopBottomJawDistance"]
    sourceToMLCDistance = machine_info["MultiLeaf"]["SourceToMLCDistance"]

    beam_sequence.BeamLimitingDeviceSequence = pydicom.sequence.Sequence()
    beam_sequence.BeamLimitingDeviceSequence.append(pydicom.dataset.Dataset())
    beam_sequence.BeamLimitingDeviceSequence.append(pydicom.dataset.Dataset())
    beam_sequence.BeamLimitingDeviceSequence.append(pydicom.dataset.Dataset())
    beam_sequence.BeamLimitingDeviceSequence[0].RTBeamLimitingDeviceType = "ASYMX"
    beam_sequence.BeamLimitingDeviceSequence[0].SourceToBeamLimitingDeviceDistance = (
        sourceToLeftRightDistance * 10
    )
    beam_sequence.BeamLimitingDeviceSequence[1].RTBeamLimitingDeviceType = "ASYMY"
    beam_sequence.BeamLimitingDeviceSequence[1].SourceToBeamLimitingDeviceDistance = (
        sourceToTopBottomDistance * 10
    )
    beam_sequence.BeamLimitingDeviceSequence[2].RTBeamLimitingDeviceType = "MLCX"
    beam_sequence.BeamLimitingDeviceSequence[2].SourceToBeamLimitingDeviceDistance = (
        sourceToMLCDistance * 10
    )
    beam_sequence.BeamLimitingDeviceSequence[0].NumberOfLeafJawPairs = "1"
    beam_sequence.BeamLimitingDeviceSequence[1].NumberOfLeafJawPairs = "1"
    beam_sequence.BeamLimitingDeviceSequence[2].NumberOfLeafJawPairs = n_points / 2

    leafPairList = machine_info["MultiLeaf"]["LeafPairList"]
    bounds = []
    for leaf_count, leaf in enumerate(leafPairList):
        leaf_width = leaf["Width"]

        if leaf_count == 0:
            # We don't get given the explicit boundary positions in the machine_info
            # instead we get the leafcenter position and the leaf width
            # so for the first leaf, we set the max boundary value, then append that + width for all leaves
            leaf_center = leaf["YCenterPosition"]
            leaf_max_boundary = leaf_center - (leaf_width / 2)
            bounds.append(leaf_max_boundary * 10)
            curr_boundary = leaf_max_boundary

        # Increment curr_boundary with current leaf width, append to bounds
        curr_boundary += leaf_width
        bounds.append(curr_boundary * 10)

    beam_sequence.BeamLimitingDeviceSequence[2].LeafPositionBoundaries = bounds

    return beam_sequence


def mapBeamControlPointSequence(
    ctrlpt_index: int,
    beam_sequence: pydicom.dataset.Dataset,
    beam_energy: int,
    sourceToSurfaceDistance: float,
    doserate: int,
    leafpositions: List,
    iso_center: str,
    gantryrotdir: str,
    gantryangle: float,
    colangle: float,
    psupportangle: float,
    numwedges: int,
    cumulativeMetersetWeight: float,
    currentMetersetWeight: float,
    x1: int,
    x2: int,
    y1: int,
    y2: int,
) -> pydicom.dataset.Dataset:
    """
    Map the controlpoint sequences of a beam to a DICOM dataset.
    Called for each controlpoint in the beam
    Returns the supplied beam_sequence DICOM dataset with the appended controlpointsequence
    """
    # append a controlpointsequence to the dicom dataset
    beam_sequence.ControlPointSequence.append(pydicom.dataset.Dataset())
    # set the current control point sequence
    currControlPointSequence = beam_sequence.ControlPointSequence[ctrlpt_index]

    currControlPointSequence.ControlPointIndex = ctrlpt_index

    # Append additional sequence fields to the ctrlpoint sequence
    currControlPointSequence.BeamLimitingDevicePositionSequence = (
        pydicom.sequence.Sequence()
    )
    currControlPointSequence.ReferencedDoseReferenceSequence = (
        pydicom.sequence.Sequence()
    )
    currControlPointSequence.ReferencedDoseReferenceSequence.append(
        pydicom.dataset.Dataset()
    )

    # set cumulative and current metersetweight
    currControlPointSequence.CumulativeMetersetWeight = cumulativeMetersetWeight
    currControlPointSequence.ReferencedDoseReferenceSequence[
        0
    ].CumulativeDoseReferenceCoefficient = currentMetersetWeight

    currControlPointSequence.ReferencedDoseReferenceSequence[
        0
    ].ReferencedDoseReferenceNumber = "1"

    # Append the dicom sequences for X, Y, MLCX jaws
    currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        pydicom.dataset.Dataset()
    )  # This will be the x jaws

    currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        pydicom.dataset.Dataset()
    )  # this will be the y jaws

    currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        pydicom.dataset.Dataset()
    )  # this will be the MLC

    # X Jaws
    currControlPointSequence.BeamLimitingDevicePositionSequence[
        0
    ].RTBeamLimitingDeviceType = "ASYMX"

    currControlPointSequence.BeamLimitingDevicePositionSequence[0].LeafJawPositions = [
        x1,
        x2,
    ]

    # Y jaws
    currControlPointSequence.BeamLimitingDevicePositionSequence[
        1
    ].RTBeamLimitingDeviceType = "ASYMY"

    currControlPointSequence.BeamLimitingDevicePositionSequence[1].LeafJawPositions = [
        y1,
        y2,
    ]

    # MLC
    currControlPointSequence.BeamLimitingDevicePositionSequence[
        2
    ].RTBeamLimitingDeviceType = "MLCX"

    currControlPointSequence.BeamLimitingDevicePositionSequence[
        2
    ].LeafJawPositions = leafpositions

    currControlPointSequence.GantryAngle = gantryangle
    currControlPointSequence.GantryRotationDirection = gantryrotdir
    currControlPointSequence.SourceToSurfaceDistance = sourceToSurfaceDistance

    if ctrlpt_index == 0:  # first control point beam meterset always zero
        currControlPointSequence.NominalBeamEnergy = beam_energy
        currControlPointSequence.DoseRateSet = doserate

        currControlPointSequence.BeamLimitingDeviceAngle = colangle

        if numwedges > 0:
            currControlPointSequence.WedgePositionSequence = pydicom.sequence.Sequence()

            currControlPointSequence.WedgePositionSequence.append(
                pydicom.dataset.Dataset()
            )
            currControlPointSequence.WedgePositionSequence[0].WedgePosition = "IN"

            currControlPointSequence.WedgePositionSequence[
                0
            ].ReferencedWedgeNumber = "1"

        currControlPointSequence.BeamLimitingDeviceRotationDirection = "NONE"

        currControlPointSequence.PatientSupportAngle = psupportangle

        currControlPointSequence.PatientSupportRotationDirection = "NONE"

        currControlPointSequence.IsocenterPosition = iso_center

    return beam_sequence


def getWedgeInfo(cp, plan):
    numwedges = 0
    wedgename = ""
    wedgeorientation = ""
    wedgeangle = ""
    wedgetype = ""
    if (
        cp["WedgeContext"]["WedgeName"] == "No Wedge"
        or cp["WedgeContext"]["WedgeName"] == ""
    ):
        # wedgeflag = False
        plan.logger.debug("Wedge is no name")
        numwedges = 0
    elif (
        "edw" in cp["WedgeContext"]["WedgeName"]
        or "EDW" in cp["WedgeContext"]["WedgeName"]
    ):
        plan.logger.debug("Wedge present")
        wedgetype = "DYNAMIC"
        # wedgeflag = True
        numwedges = 1
        wedgeangle = cp["WedgeContext"]["Angle"]
        wedgeinorout = ""
        wedgeinorout = cp["WedgeContext"]["Orientation"]
        if wedgeinorout == "WedgeBottomToTop":
            wedgename = f"{cp['WedgeContext']['WedgeName'].upper()}{wedgeangle}IN"
            wedgeorientation = "0"  # temporary until I find out what to put here
        elif wedgeinorout == "WedgeTopToBottom":
            wedgename = f"{cp['WedgeContext']['WedgeName'].upper()}{wedgeangle}OUT"
            wedgeorientation = "180"
        plan.logger.debug("Wedge name = %s", wedgename)
    elif "UP" in cp["WedgeContext"]["WedgeName"]:
        plan.logger.debug("Wedge present")
        wedgetype = "STANDARD"
        # wedgeflag = True
        numwedges = 1
        wedgeangle = cp["WedgeContext"]["Angle"]
        wedgeinorout = ""
        wedgeinorout = cp["WedgeContext"]["Orientation"]
        if int(wedgeangle) == 15:
            numberinname = "30"
        elif int(wedgeangle) == 45:
            numberinname = "20"
        elif int(wedgeangle) == 30:
            numberinname = "30"
        elif int(wedgeangle) == 60:
            numberinname = "15"
        if wedgeinorout == "WedgeRightToLeft":
            wedgename = f"W{int(wedgeangle)}R{numberinname}"
            wedgeorientation = "90"  # temporary until I find out what to put here
        elif wedgeinorout == "WedgeLeftToRight":
            wedgename = f"W{int(wedgeangle)}L{numberinname}"
            wedgeorientation = "270"
        elif wedgeinorout == "WedgeTopToBottom":
            wedgename = f"W{int(wedgeangle)}OUT{numberinname}"
            wedgeorientation = "180"  # temporary until I find out what to put here
        elif wedgeinorout == "WedgeBottomToTop":
            wedgename = f"W{int(wedgeangle)}IN{numberinname}"
            wedgeorientation = "0"  # temporary until I find out what to put here
        plan.logger.debug("Wedge name = %s", wedgename)

    return numwedges, wedgename, wedgeorientation, wedgeangle, wedgetype
