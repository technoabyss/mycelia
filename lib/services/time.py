import typing
import datetime
import re

from discord.ext import commands

from lib.utils.etc import Service
from lib.utils.checks import in_guild

# Dict of UTC offsets -> associated timezone abbreviations
tzlist = {
  "-12":    { "BIT", "IDLW" },
  "-11":    { "NUT" },
  "-10":    { "CKT", "HST", "SDT", "TAHT" },
  "-09:30": { "MART", "MIT" },
  "-09":    { "AKST", "GAMT", "GIT", "HDT" },
  "-08":    { "AKDT", "CIST", "PST" },
  "-07":    { "MST", "PDT" },
  "-06":    { "CST", "EAST", "GALT", "MDT" },
  "-05":    { "ACT", "CDT", "COT", "EASST", "EST", "PET" },
  "-04":    { "BOT", "CLT", "COST", "ECT", "EDT", "FKT", "GYT", "PYT", "VET" },
  "-03:30": { "NST", "NT" },
  "-03":    { "ADT", "AMST", "ART", "BRT", "CLST", "FKST", "GFT", "PMST", "PYST", "ROTT", "SRT", "UYT", "WGT" },
  "-02:30": { "NDT" },
  "-02":    { "BRST", "FNT", "PMDT", "UYST", "WGST" },
  "-01":    { "AZOT", "CVT", "EGT" },
  "+0":     { "AZOST", "EGST", "GMT", "UTC", "WET" },
  "+01":    { "BST", "CET", "DFT", "MET", "WAT", "WEST" },
  "+02":    { "CAT", "CEST", "EET", "HAEC", "KALT", "MEST", "SAST", "WAST" },
  "+03":    { "AST", "EAT", "EEST", "FET", "IDT", "IOT", "MSK", "SYOT", "TRT" },
  "+03:30": { "IRST" },
  "+04":    { "AMT", "AZT", "GET", "GST", "MUT", "RET", "SAMT", "SCT", "VOLT" },
  "+04:30": { "AFT", "IRDT" },
  "+05":    { "AQTT", "HMT", "MAWT", "MVT", "ORAT", "PKT", "TFT", "TJT", "TMT", "UZT", "YEKT" },
  "+05:30": { "IST", "SLST" },
  "+05:45": { "NPT" },
  "+06":    { "ALMT", "BIOT", "BTT", "KGT", "OMST", "VOST" },
  "+06:30": { "CCT", "MMT" },
  "+07":    { "CXT", "DAVT", "HOVT", "ICT", "KRAT", "NOVT", "THA", "WIT" },
  "+08":    { "BDT", "CHOT", "CIT", "CT", "HKT", "HOVST", "IRKT", "MYT", "PHT", "SGT", "SST", "ULAT", "WST", "AWST" },
  "+08:45": { "ACWST", "CWST" },
  "+09":    { "CHOST", "EIT", "JST", "KST", "TLT", "ULAST", "YAKT" },
  "+09:30": { "ACST" },
  "+10":    { "AEST", "CHST", "CHUT", "DDUT", "PGT", "VLAT" },
  "+10:30": { "ACDT", "LHST" },
  "+11":    { "AEDT", "KOST", "MIST", "NCT", "NFT", "PONT", "SAKT", "SBT", "SRET", "VUT" },
  "+12":    { "ANAT", "FJT", "GILT", "MAGT", "MHT", "NZST", "PETT", "TVT", "WAKT" },
  "+12:45": { "CHAST" },
  "+13":    { "NZDT", "PHOT", "TKT", "TOT" },
  "+13:45": { "CHADT" },
  "+14":    { "LINT" }
}
# Convert to lookup table
tztable = {}
for offset, abbreviations in tzlist.items():
  # Plus or minus
  if offset[0] == "-": prefix = -1
  else:                prefix = +1

  # Hours
  hrs = int(offset[1:3])

  # Minutes
  if len(offset) > 3: mins = int(offset[4:6])
  else:               mins = 0

  # Assign delta to abbreviation
  for abbr in abbreviations:
    tztable[abbr] = prefix * datetime.timedelta(hours=hrs, minutes=mins)

# Alternative formatting for timedelta
def timedelta_to_str(delta: datetime.timedelta) -> str:
  if delta < datetime.timedelta(0): out = "-"
  else:                             out = "+"
  # Adapted from datetime.timedelta.__str__
  delta = abs(delta)
  mm = delta.seconds // 60
  hh, mm = divmod(mm, 60)
  if hh == 0 and mm == 0: return ""
  if delta.days: out += "%dd" % delta.days
  out += "%d" % hh
  if mm: out += ":%02d" % mm
  return out

class Time(Service):
  # Guild-only
  async def cog_check(self, ctx: commands.Context):
    return in_guild(ctx)

  @commands.group(aliases=["t"], invoke_without_command=True)
  async def time(self, ctx: commands.Context, *, _input: typing.Optional[str] = "UTC"):
    """ Show the current time, in UTC by default. """

    # Parse input
    # https://rubular.com/r/VzejTpqLv1g9rB
    match = re.match(
      r"^([a-z]+)(\s*([+-])?((\d{1,2})(:(\d{2}))?)?)$", _input, re.IGNORECASE)

    if match:
      tz = match[1].upper()
      try:
        utc_offset = tztable[tz]
      except KeyError as exc:
        await ctx.reply(f"Timezone {exc} not found.", mention_author=False)
        return

      if match[2]:

        if match[7]: mins = match[7]
        else:        mins = "00"

        try:
          t = datetime.datetime.strptime(f"{match[5].rjust(2, '0')}:{mins}", "%H:%M")
        except ValueError as exc:
          await ctx.reply(exc, mention_author=False)
          return

        delta = prefix * datetime.timedelta(hours=t.hour, minutes=t.minute)
      else:
        delta = datetime.timedelta(0)

      _utc_offset = ""
      if tz != "UTC":
        _utc_offset = f" (UTC{timedelta_to_str(utc_offset + delta)})"

      time = datetime.datetime.utcnow() + utc_offset + delta
      await ctx.send(time.strftime(f"%I:%M%p {tz}{timedelta_to_str(delta)}{_utc_offset}"))
    else:
      await ctx.reply(f"That's definitely not a timezone. Try something like \"EST+5\".", mention_author=False)

  # @time.command(aliases=["conv"])
  # async def convert(self, ctx, *, ):
  #   """ Converts time between two timezones """
  #   # ,time convert <time> <timezone> [["to"] <timezone>]
  #   # await ctx.send(datetime.datetime.utcnow().strftime("%I:%M%p (%Z)"))
  #   # ,t conv 2PM EST-2 to UTC+1
  #   # ,t conv 5AM GMT+5
  #   # parser.parse("Tue May 08 15:14:45 +0800 2012")
  #   pass
