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

    for beam_count, beam in enumerate(beam_list):
        # print(beam_list)
        with open("/home/neil/beam.json", "w") as tfile:
            print("beam_baby")
            json.dump(beam, tfile)
        print("should be 2")
        print(beam_count)

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
        currentmeterset = 0.0
        metercount = 0
        plan.logger.debug("Number of control points: %s", numctrlpts)

        # Loop through the cp indices and map them to dicom
        for cp_index, cp in enumerate(cp_manager["ControlPointList"]):

            metersetweight.append(cp["Weight"])

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
            numwedges = 0
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
                    wedgename = (
                        f"{cp['WedgeContext']['WedgeName'].upper()}{wedgeangle}IN"
                    )
                    wedgeorientation = (
                        "0"  # temporary until I find out what to put here
                    )
                elif wedgeinorout == "WedgeTopToBottom":
                    wedgename = (
                        f"{cp['WedgeContext']['WedgeName'].upper()}{wedgeangle}OUT"
                    )
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
                    wedgeorientation = (
                        "90"  # temporary until I find out what to put here
                    )
                elif wedgeinorout == "WedgeLeftToRight":
                    wedgename = f"W{int(wedgeangle)}L{numberinname}"
                    wedgeorientation = "270"
                elif wedgeinorout == "WedgeTopToBottom":
                    wedgename = f"W{int(wedgeangle)}OUT{numberinname}"
                    wedgeorientation = (
                        "180"  # temporary until I find out what to put here
                    )
                elif wedgeinorout == "WedgeBottomToTop":
                    wedgename = f"W{int(wedgeangle)}IN{numberinname}"
                    wedgeorientation = (
                        "0"  # temporary until I find out what to put here
                    )
                plan.logger.debug("Wedge name = %s", wedgename)

            # TODO
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

            # TODO

            beam_sequence = mapBeamDeviceLimitingSequence(beam_sequence, n_points)

            if (
                "STEP" in beam["SetBeamType"].upper()
                and "SHOOT" in beam["SetBeamType"].upper()
            ):
                print("STEP BABAY")

                ctrlpt_range = numctrlpts * 2
                is_stepwise = True

                if cp_index % 2 == 1:
                    currentmeterset = currentmeterset + float(
                        metersetweight[metercount]
                    )
                    metercount += 1

            else:
                print("NOT STEPWISE")
                ctrlpt_range = numctrlpts
                is_stepwise = False

            # for ctrlpt_index in range(0, ctrlpt_range):
            beam_sequence = mapBeamControlPointSequence(
                cp_index,
                beam,
                beam_sequence,
                beam_energy,
                doserate,
                leafpositions,
                plan.iso_center,
                gantryrotdir,
                gantryangle,
                colangle,
                psupportangle,
                numwedges,
                numctrlpts,
                metersetweight,
                currentmeterset,
                x1,
                x2,
                y1,
                y2,
                is_stepwise,
            )
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
        # if (
        #     "STEP" in beam["SetBeamType"].upper()
        #     and "SHOOT" in beam["SetBeamType"].upper()
        # ):
        #     print("STEP BABAY")
        #     plan.logger.debug("Using Step & Shoot")

        #     beam_sequence.NumberOfControlPoints = numctrlpts * 2
        #     beam_sequence.SourceToSurfaceDistance = beam["SSD"] * 10

        #     if numwedges > 0:
        #         ds.BeamSequence[beam_count].WedgeSequence = pydicom.sequence.Sequence()
        #         beam_sequence.WedgeSequence.append(
        #             pydicom.dataset.Dataset()
        #         )  # I am assuming only one wedge per beam (which makes sense because you can't change it during beam)
        #         beam_sequence.WedgeSequence[
        #             0
        #         ].WedgeNumber = 1  # might need to change this
        #         beam_sequence.WedgeSequence[0].WedgeType = wedgetype
        #         beam_sequence.WedgeSequence[0].WedgeAngle = wedgeangle
        #         beam_sequence.WedgeSequence[0].WedgeID = wedgename
        #         beam_sequence.WedgeSequence[0].WedgeOrientation = wedgeorientation
        #         beam_sequence.WedgeSequence[0].WedgeFactor = ""

        #     metercount = 1
        #     for j in range(0, numctrlpts * 2):

        #         # append a controlpointsequence to the dicom dataset
        #         beam_sequence.ControlPointSequence.append(pydicom.dataset.Dataset())
        #         # set the current control point sequence
        #         currControlPointSequence = beam_sequence.ControlPointSequence[j]

        #         currControlPointSequence.ControlPointIndex = j
        #         currControlPointSequence.BeamLimitingDevicePositionSequence = (
        #             pydicom.sequence.Sequence()
        #         )
        #         currControlPointSequence.ReferencedDoseReferenceSequence = (
        #             pydicom.sequence.Sequence()
        #         )
        #         currControlPointSequence.ReferencedDoseReferenceSequence.append(
        #             pydicom.dataset.Dataset()
        #         )
        #         if j % 2 == 1:  # odd number control point
        #             currentmeterset = currentmeterset + float(
        #                 metersetweight[metercount]
        #             )
        #             metercount = metercount + 1

        #         currControlPointSequence.CumulativeMetersetWeight = currentmeterset
        #         currControlPointSequence.ReferencedDoseReferenceSequence[
        #             0
        #         ].CumulativeDoseReferenceCoefficient = currentmeterset
        #         currControlPointSequence.ReferencedDoseReferenceSequence[
        #             0
        #         ].ReferencedDoseReferenceNumber = "1"

        #         currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        #             pydicom.dataset.Dataset()
        #         )  # This will be the x jaws

        #         currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        #             pydicom.dataset.Dataset()
        #         )  # this will be the y jaws

        #         currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             0
        #         ].RTBeamLimitingDeviceType = "ASYMX"

        #         currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             0
        #         ].LeafJawPositions = [x1, x2]

        #         currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             1
        #         ].RTBeamLimitingDeviceType = "ASYMY"

        #         currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             1
        #         ].LeafJawPositions = [y1, y2]

        #         # MLC
        #         currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        #             pydicom.dataset.Dataset()
        #         )  # this will be the MLC
        #         currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             2
        #         ].RTBeamLimitingDeviceType = "MLCX"

        #         currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             2
        #         ].LeafJawPositions = leafpositions[j]

        #         if j == 0:  # first control point beam meterset always zero
        #             currControlPointSequence.NominalBeamEnergy = beam_energy
        #             currControlPointSequence.DoseRateSet = doserate

        #             currControlPointSequence.GantryRotationDirection = "NONE"
        #             currControlPointSequence.GantryAngle = gantryangle
        #             currControlPointSequence.BeamLimitingDeviceAngle = colangle
        #             currControlPointSequence.BeamLimitingDeviceRotationDirection = (
        #                 "NONE"
        #             )
        #             currControlPointSequence.SourceToSurfaceDistance = beam["SSD"] * 10

        #             if numwedges > 0:
        #                 currControlPointSequence.WedgePositionSequence = (
        #                     pydicom.sequence.Sequence()
        #                 )

        #                 currControlPointSequence.WedgePositionSequence.append(
        #                     pydicom.dataset.Dataset()
        #                 )
        #                 currControlPointSequence.WedgePositionSequence[
        #                     0
        #                 ].WedgePosition = "IN"

        #                 currControlPointSequence.WedgePositionSequence[
        #                     0
        #                 ].ReferencedWedgeNumber = "1"

        #             # currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        #             #     pydicom.dataset.Dataset()
        #             # )  # This will be the x jaws

        #             # currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        #             #     pydicom.dataset.Dataset()
        #             # )  # this will be the y jaws

        #             # currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             #     0
        #             # ].RTBeamLimitingDeviceType = "ASYMX"

        #             # currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             #     0
        #             # ].LeafJawPositions = [x1, x2]

        #             # currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             #     1
        #             # ].RTBeamLimitingDeviceType = "ASYMY"

        #             # currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             #     1
        #             # ].LeafJawPositions = [y1, y2]

        #             # # MLC
        #             # currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        #             #     pydicom.dataset.Dataset()
        #             # )  # this will be the MLC
        #             # currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             #     2
        #             # ].RTBeamLimitingDeviceType = "MLCX"

        #             # currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             #     2
        #             # ].LeafJawPositions = leafpositions[j]

        #             currControlPointSequence.SourceToSurfaceDistance = beam["SSD"] * 10

        #             currControlPointSequence.BeamLimitingDeviceRotationDirection = (
        #                 "NONE"
        #             )

        #             currControlPointSequence.PatientSupportAngle = psupportangle

        #             currControlPointSequence.PatientSupportRotationDirection = "NONE"

        #             currControlPointSequence.IsocenterPosition = plan.iso_center

        #             currControlPointSequence.GantryRotationDirection = gantryrotdir

        #         # else:
        #         #     currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        #         #         pydicom.dataset.Dataset()
        #         #     )  # This will be the mlcs for control points other than the first

        #         #     currControlPointSequence.BeamLimitingDevicePositionSequence[
        #         #         0
        #         #     ].RTBeamLimitingDeviceType = "MLCX"

        #         #     currControlPointSequence.BeamLimitingDevicePositionSequence[
        #         #         0
        #         #     ].LeafJawPositions = leafpositions[j]

        #         ds.BeamSequence[
        #             beam_count
        #         ].NumberOfWedges = (
        #             numwedges  # this is temporary value, will read in from file later
        #         )

        #         ds.BeamSequence[beam_count].NumberOfCompensators = "0"  # Also temporary
        #         beam_sequence.NumberOfBoli = "0"
        #         beam_sequence.NumberOfBlocks = "0"  # Temp

        #         # BamLimitingDeviceSequence
        #         ds.BeamSequence[
        #             beam_count
        #         ].BeamLimitingDeviceSequence = pydicom.sequence.Sequence()

        #         beam_sequence.BeamLimitingDeviceSequence.append(
        #             pydicom.dataset.Dataset()
        #         )
        #         beam_sequence.BeamLimitingDeviceSequence.append(
        #             pydicom.dataset.Dataset()
        #         )
        #         beam_sequence.BeamLimitingDeviceSequence.append(
        #             pydicom.dataset.Dataset()
        #         )

        #         beam_sequence.BeamLimitingDeviceSequence[
        #             0
        #         ].RTBeamLimitingDeviceType = "ASYMX"

        #         beam_sequence.BeamLimitingDeviceSequence[
        #             1
        #         ].RTBeamLimitingDeviceType = "ASYMY"

        #         beam_sequence.BeamLimitingDeviceSequence[
        #             2
        #         ].RTBeamLimitingDeviceType = "MLCX"

        #         beam_sequence.BeamLimitingDeviceSequence[0].NumberOfLeafJawPairs = "1"
        #         beam_sequence.BeamLimitingDeviceSequence[1].NumberOfLeafJawPairs = "1"
        #         beam_sequence.BeamLimitingDeviceSequence[2].NumberOfLeafJawPairs = (
        #             p_count / 2
        #         )
        #         bounds = [
        #             "-200",
        #             "-190",
        #             "-180",
        #             "-170",
        #             "-160",
        #             "-150",
        #             "-140",
        #             "-130",
        #             "-120",
        #             "-110",
        #             "-100",
        #             "-95",
        #             "-90",
        #             "-85",
        #             "-80",
        #             "-75",
        #             "-70",
        #             "-65",
        #             "-60",
        #             "-55",
        #             "-50",
        #             "-45",
        #             "-40",
        #             "-35",
        #             "-30",
        #             "-25",
        #             "-20",
        #             "-15",
        #             "-10",
        #             "-5",
        #             "0",
        #             "5",
        #             "10",
        #             "15",
        #             "20",
        #             "25",
        #             "30",
        #             "35",
        #             "40",
        #             "45",
        #             "50",
        #             "55",
        #             "60",
        #             "65",
        #             "70",
        #             "75",
        #             "80",
        #             "85",
        #             "90",
        #             "95",
        #             "100",
        #             "110",
        #             "120",
        #             "130",
        #             "140",
        #             "150",
        #             "160",
        #             "170",
        #             "180",
        #             "190",
        #             "200",
        #         ]
        #         beam_sequence.BeamLimitingDeviceSequence[
        #             2
        #         ].LeafPositionBoundaries = bounds
        # else:
        #     print("NO STEP")
        #     plan.logger.debug("Not using Step & Shoot")
        #     beam_sequence.NumberOfControlPoints = numctrlpts + 1
        #     beam_sequence.SourceToSurfaceDistance = beam["SSD"] * 10
        #     if numwedges > 0:
        #         ds.BeamSequence[beam_count].WedgeSequence = pydicom.sequence.Sequence()
        #         beam_sequence.WedgeSequence.append(pydicom.dataset.Dataset())
        #         # I am assuming only one wedge per beam (which makes sense
        #         # because you can't change it during beam)
        #         beam_sequence.WedgeSequence[0].WedgeNumber = 1
        #         # might need to change this
        #         beam_sequence.WedgeSequence[0].WedgeType = wedgetype
        #         beam_sequence.WedgeSequence[0].WedgeAngle = wedgeangle
        #         beam_sequence.WedgeSequence[0].WedgeID = wedgename
        #         beam_sequence.WedgeSequence[0].WedgeOrientation = wedgeorientation
        #         beam_sequence.WedgeSequence[0].WedgeFactor = ""

        #     for j in range(0, numctrlpts):
        #         beam_sequence.ControlPointSequence.append(pydicom.dataset.Dataset())
        #         currControlPointSequence = beam_sequence.ControlPointSequence[j]
        #         currControlPointSequence.ControlPointIndex = j
        #         currControlPointSequence.BeamLimitingDevicePositionSequence = (
        #             pydicom.sequence.Sequence()
        #         )
        #         currControlPointSequence.ReferencedDoseReferenceSequence = (
        #             pydicom.sequence.Sequence()
        #         )
        #         currControlPointSequence.ReferencedDoseReferenceSequence.append(
        #             pydicom.dataset.Dataset()
        #         )
        #         currControlPointSequence.CumulativeMetersetWeight = metersetweight[j]
        #         currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        #             pydicom.dataset.Dataset()
        #         )  # This will be the x jaws
        #         currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        #             pydicom.dataset.Dataset()
        #         )  # this will be the y jaws
        #         currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             0
        #         ].RTBeamLimitingDeviceType = "ASYMX"
        #         currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             0
        #         ].LeafJawPositions = [x1, x2]
        #         currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             1
        #         ].RTBeamLimitingDeviceType = "ASYMY"
        #         currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             1
        #         ].LeafJawPositions = [y1, y2]
        #         currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        #             pydicom.dataset.Dataset()
        #         )  # this will be the MLC
        #         currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             2
        #         ].RTBeamLimitingDeviceType = "MLCX"
        #         currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             2
        #         ].LeafJawPositions = leafpositions[j]

        #         if j == 0:  # first control point beam meterset always zero
        #             currControlPointSequence.NominalBeamEnergy = beam_energy
        #             currControlPointSequence.DoseRateSet = doserate

        #             currControlPointSequence.GantryRotationDirection = "NONE"
        #             currControlPointSequence.GantryAngle = gantryangle
        #             currControlPointSequence.BeamLimitingDeviceAngle = colangle
        #             currControlPointSequence.SourceToSurfaceDistance = beam["SSD"] * 10

        #             # NOT IN STEP
        #             currControlPointSequence.ReferencedDoseReferenceSequence[
        #                 0
        #             ].CumulativeDoseReferenceCoefficient = "0"
        #             currControlPointSequence.ReferencedDoseReferenceSequence[
        #                 0
        #             ].ReferencedDoseReferenceNumber = "1"

        #             if numwedges > 0:
        #                 WedgePosition1 = pydicom.dataset.Dataset()
        #                 currControlPointSequence.WedgePositionSequence = (
        #                     pydicom.sequence.Sequence()
        #                 )
        #                 currControlPointSequence.WedgePositionSequence.append(
        #                     WedgePosition1
        #                 )
        #                 currControlPointSequence.WedgePositionSequence[
        #                     0
        #                 ].WedgePosition = "IN"
        #                 currControlPointSequence.WedgePositionSequence[
        #                     0
        #                 ].ReferencedWedgeNumber = "1"
        #             # currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        #             #     pydicom.dataset.Dataset()
        #             # )  # This will be the x jaws
        #             # currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        #             #     pydicom.dataset.Dataset()
        #             # )  # this will be the y jaws
        #             # currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             #     0
        #             # ].RTBeamLimitingDeviceType = "ASYMX"
        #             # currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             #     0
        #             # ].LeafJawPositions = [x1, x2]
        #             # currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             #     1
        #             # ].RTBeamLimitingDeviceType = "ASYMY"
        #             # currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             #     1
        #             # ].LeafJawPositions = [y1, y2]
        #             # currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        #             #     pydicom.dataset.Dataset()
        #             # )  # this will be the MLC
        #             # currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             #     2
        #             # ].RTBeamLimitingDeviceType = "MLCX"
        #             # currControlPointSequence.BeamLimitingDevicePositionSequence[
        #             #     2
        #             # ].LeafJawPositions = leafpositions[j]
        #             currControlPointSequence.SourceToSurfaceDistance = beam["SSD"] * 10
        #             currControlPointSequence.BeamLimitingDeviceRotationDirection = (
        #                 "NONE"
        #             )
        #             currControlPointSequence.PatientSupportAngle = psupportangle
        #             currControlPointSequence.PatientSupportRotationDirection = "NONE"
        #             currControlPointSequence.IsocenterPosition = plan.iso_center
        #             currControlPointSequence.GantryRotationDirection = gantryrotdir
        #             beam_sequence.NumberOfWedges = numwedges

        #             ds.BeamSequence[
        #                 beam_count
        #             ].NumberOfCompensators = (
        #                 "0"  # this is temporary value, will read in from file later
        #             )
        #             beam_sequence.NumberOfBoli = "0"  # Also temporary
        #             beam_sequence.NumberOfBlocks = "0"  # Temp
        #         # else:
        #         #     # print(f"LEAF POSITIONS: {leafpositions}")
        #         #     # print(f"JJJ: {j}")
        #         #     # This will be the mlcs for control points other than the first
        #         #     # currControlPointSequence.BeamLimitingDevicePositionSequence.append(
        #         #     #     pydicom.dataset.Dataset()
        #         #     # )
        #         #     # # next
        #         #     # currControlPointSequence.BeamLimitingDevicePositionSequence[
        #         #     #     0
        #         #     # ].RTBeamLimitingDeviceType = "MLCX"

        #         #     # # next
        #         #     # currControlPointSequence.BeamLimitingDevicePositionSequence[
        #         #     #     0
        #         #     # ].LeafJawPositions = list_get(leafpositions, j, None)

        #         #     # next
        #         #     currControlPointSequence.ReferencedDoseReferenceSequence[
        #         #         0
        #         #     ].CumulativeDoseReferenceCoefficient = "1"
        #         #     currControlPointSequence.ReferencedDoseReferenceSequence[
        #         #         0
        #         #     ].ReferencedDoseReferenceNumber = "1"

        #         ds.BeamSequence[
        #             beam_count
        #         ].BeamLimitingDeviceSequence = pydicom.sequence.Sequence()
        #         beam_sequence.BeamLimitingDeviceSequence.append(
        #             pydicom.dataset.Dataset()
        #         )
        #         beam_sequence.BeamLimitingDeviceSequence.append(
        #             pydicom.dataset.Dataset()
        #         )
        #         beam_sequence.BeamLimitingDeviceSequence.append(
        #             pydicom.dataset.Dataset()
        #         )
        #         beam_sequence.BeamLimitingDeviceSequence[
        #             0
        #         ].RTBeamLimitingDeviceType = "ASYMX"
        #         beam_sequence.BeamLimitingDeviceSequence[
        #             1
        #         ].RTBeamLimitingDeviceType = "ASYMY"
        #         beam_sequence.BeamLimitingDeviceSequence[
        #             2
        #         ].RTBeamLimitingDeviceType = "MLCX"
        #         beam_sequence.BeamLimitingDeviceSequence[0].NumberOfLeafJawPairs = "1"
        #         beam_sequence.BeamLimitingDeviceSequence[1].NumberOfLeafJawPairs = "1"
        #         beam_sequence.BeamLimitingDeviceSequence[2].NumberOfLeafJawPairs = (
        #             p_count / 2
        #         )
        #         bounds = [
        #             "-200",
        #             "-190",
        #             "-180",
        #             "-170",
        #             "-160",
        #             "-150",
        #             "-140",
        #             "-130",
        #             "-120",
        #             "-110",
        #             "-100",
        #             "-95",
        #             "-90",
        #             "-85",
        #             "-80",
        #             "-75",
        #             "-70",
        #             "-65",
        #             "-60",
        #             "-55",
        #             "-50",
        #             "-45",
        #             "-40",
        #             "-35",
        #             "-30",
        #             "-25",
        #             "-20",
        #             "-15",
        #             "-10",
        #             "-5",
        #             "0",
        #             "5",
        #             "10",
        #             "15",
        #             "20",
        #             "25",
        #             "30",
        #             "35",
        #             "40",
        #             "45",
        #             "50",
        #             "55",
        #             "60",
        #             "65",
        #             "70",
        #             "75",
        #             "80",
        #             "85",
        #             "90",
        #             "95",
        #             "100",
        #             "110",
        #             "120",
        #             "130",
        #             "140",
        #             "150",
        #             "160",
        #             "170",
        #             "180",
        #             "190",
        #             "200",
        #         ]
        #         beam_sequence.BeamLimitingDeviceSequence[
        #             2
        #         ].LeafPositionBoundaries = bounds
        #     numwedges = 0

        # Get the prescription for this beam
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


def mapBeamDeviceLimitingSequence(beam_sequence, n_points):
    beam_sequence.BeamLimitingDeviceSequence = pydicom.sequence.Sequence()
    beam_sequence.BeamLimitingDeviceSequence.append(pydicom.dataset.Dataset())
    beam_sequence.BeamLimitingDeviceSequence.append(pydicom.dataset.Dataset())
    beam_sequence.BeamLimitingDeviceSequence.append(pydicom.dataset.Dataset())
    beam_sequence.BeamLimitingDeviceSequence[0].RTBeamLimitingDeviceType = "ASYMX"
    beam_sequence.BeamLimitingDeviceSequence[1].RTBeamLimitingDeviceType = "ASYMY"
    beam_sequence.BeamLimitingDeviceSequence[2].RTBeamLimitingDeviceType = "MLCX"
    beam_sequence.BeamLimitingDeviceSequence[0].NumberOfLeafJawPairs = "1"
    beam_sequence.BeamLimitingDeviceSequence[1].NumberOfLeafJawPairs = "1"
    beam_sequence.BeamLimitingDeviceSequence[2].NumberOfLeafJawPairs = n_points / 2
    bounds = [
        "-200",
        "-190",
        "-180",
        "-170",
        "-160",
        "-150",
        "-140",
        "-130",
        "-120",
        "-110",
        "-100",
        "-95",
        "-90",
        "-85",
        "-80",
        "-75",
        "-70",
        "-65",
        "-60",
        "-55",
        "-50",
        "-45",
        "-40",
        "-35",
        "-30",
        "-25",
        "-20",
        "-15",
        "-10",
        "-5",
        "0",
        "5",
        "10",
        "15",
        "20",
        "25",
        "30",
        "35",
        "40",
        "45",
        "50",
        "55",
        "60",
        "65",
        "70",
        "75",
        "80",
        "85",
        "90",
        "95",
        "100",
        "110",
        "120",
        "130",
        "140",
        "150",
        "160",
        "170",
        "180",
        "190",
        "200",
    ]
    beam_sequence.BeamLimitingDeviceSequence[2].LeafPositionBoundaries = bounds

    return beam_sequence


def mapBeamControlPointSequence(
    ctrlpt_index,
    beam,
    beam_sequence,
    beam_energy,
    doserate,
    leafpositions,
    iso_center,
    gantryrotdir,
    gantryangle,
    colangle,
    psupportangle,
    numwedges,
    numctrlpts,
    metersetweight,
    currentmeterset,
    x1,
    x2,
    y1,
    y2,
    is_stepwise,
):
    print(ctrlpt_index)
    print(f"X: {[x1, x2]}")
    print(f"Y: {[y1, y2]}")
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

    # if is_stepwise and ctrlpt_index % 2 == 1:  # odd number control point
    #     if not metercount:
    #         metercount = 1
    #     currentmeterset = currentmeterset + float(metersetweight[metercount])
    #     metercount += 1

    currControlPointSequence.CumulativeMetersetWeight = currentmeterset
    currControlPointSequence.ReferencedDoseReferenceSequence[
        0
    ].CumulativeDoseReferenceCoefficient = currentmeterset

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

    if ctrlpt_index == 0:  # first control point beam meterset always zero
        currControlPointSequence.NominalBeamEnergy = beam_energy
        currControlPointSequence.DoseRateSet = doserate

        currControlPointSequence.GantryRotationDirection = "NONE"
        currControlPointSequence.GantryAngle = gantryangle
        currControlPointSequence.BeamLimitingDeviceAngle = colangle
        currControlPointSequence.BeamLimitingDeviceRotationDirection = "NONE"
        currControlPointSequence.SourceToSurfaceDistance = beam["SSD"] * 10

        if numwedges > 0:
            currControlPointSequence.WedgePositionSequence = pydicom.sequence.Sequence()

            currControlPointSequence.WedgePositionSequence.append(
                pydicom.dataset.Dataset()
            )
            currControlPointSequence.WedgePositionSequence[0].WedgePosition = "IN"

            currControlPointSequence.WedgePositionSequence[
                0
            ].ReferencedWedgeNumber = "1"

        currControlPointSequence.SourceToSurfaceDistance = beam["SSD"] * 10

        currControlPointSequence.BeamLimitingDeviceRotationDirection = "NONE"

        currControlPointSequence.PatientSupportAngle = psupportangle

        currControlPointSequence.PatientSupportRotationDirection = "NONE"

        currControlPointSequence.IsocenterPosition = iso_center

        currControlPointSequence.GantryRotationDirection = gantryrotdir

    return beam_sequence
